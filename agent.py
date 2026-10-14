import json
import os

from dotenv import load_dotenv
from groq import Groq

from tools import compute_severity, flag_for_reinspection, get_area_history

load_dotenv()
client = Groq(api_key=os.getenv("GROQ_API_KEY"))
MODEL = "openai/gpt-oss-120b"

LOCATION_PARAM = {
    "type": "string",
    "description": "Exact location name, for example 'Dwarka Sector 10 Market'",
}

TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "get_area_history",
            "description": "Get the past garbage readings (date, count, coverage) for a location.",
            "parameters": {
                "type": "object",
                "properties": {"location": LOCATION_PARAM},
                "required": ["location"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "compute_severity",
            "description": (
                "Analyse a location's readings and return its trend status "
                "(new_hotspot, chronic_hotspot, worsening, improving, stable_low, "
                "resolved, clean) and a priority (high, medium, low, none)."
            ),
            "parameters": {
                "type": "object",
                "properties": {"location": LOCATION_PARAM},
                "required": ["location"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "flag_for_reinspection",
            "description": (
                "Mark a location so a field team revisits it. "
                "Only use this when the situation justifies sending someone."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "location": LOCATION_PARAM,
                    "reason": {
                        "type": "string",
                        "description": "One sentence explaining why, including the numbers that justify it.",
                    },
                },
                "required": ["location", "reason"],
            },
        },
    },
]

FUNCTIONS = {
    "get_area_history": get_area_history,
    "compute_severity": compute_severity,
    "flag_for_reinspection": flag_for_reinspection,
}

SYSTEM_PROMPT = """You are a waste-monitoring agent for Delhi. You receive a new
garbage detection for one location and decide what to do about it.

Use your tools to investigate the location before deciding. Do not guess its
history, check it. Flag a location for reinspection only when it is a new
hotspot, a chronic hotspot, or clearly worsening. Do not flag locations that
are clean, resolved, improving or stable at a low level.

Actions only happen when you call a tool. Never say you flagged a location
unless you actually called flag_for_reinspection in this conversation.

When you are done, reply in 2-3 plain sentences: what you found, what action
you took (or why you took none), and the numbers that justify it."""


def run_agent(location, detection, max_steps=8):
    messages = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {
            "role": "user",
            "content": (
                f"A new street photo at '{location}' was processed. "
                f"Detection result: {json.dumps(detection)}. Decide what to do."
            ),
        },
    ]
    trace = []
    corrected = False

    for _ in range(max_steps):
        response = client.chat.completions.create(
            model=MODEL,
            messages=messages,
            tools=TOOLS,
            tool_choice="auto",
        )
        msg = response.choices[0].message

        if not msg.tool_calls:
            claimed_flag = "flagged" in (msg.content or "").lower()
            did_flag = any(s["tool"] == "flag_for_reinspection" for s in trace)
            if claimed_flag and not did_flag and not corrected:
                corrected = True
                messages.append({"role": "assistant", "content": msg.content or ""})
                messages.append(
                    {
                        "role": "user",
                        "content": (
                            "Check your answer against the tools you actually called. "
                            "You mention flagging, but flag_for_reinspection was never called. "
                            "If this location should be flagged, call the tool now. "
                            "Otherwise correct your answer to say that no flag was made."
                        ),
                    }
                )
                continue
            return msg.content, trace

        messages.append(
            {
                "role": "assistant",
                "content": msg.content or "",
                "tool_calls": [
                    {
                        "id": tc.id,
                        "type": "function",
                        "function": {
                            "name": tc.function.name,
                            "arguments": tc.function.arguments,
                        },
                    }
                    for tc in msg.tool_calls
                ],
            }
        )

        for tc in msg.tool_calls:
            name = tc.function.name
            args = {}
            try:
                args = json.loads(tc.function.arguments)
                result = FUNCTIONS[name](**args)
            except Exception as e:
                result = {"error": str(e)}

            trace.append({"tool": name, "args": args, "result": result})
            messages.append(
                {
                    "role": "tool",
                    "tool_call_id": tc.id,
                    "content": json.dumps(result),
                }
            )

    return "Stopped: the agent used too many steps.", trace