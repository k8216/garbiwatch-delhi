import base64
import io
import json
import os
import re

from dotenv import load_dotenv
from groq import Groq
from PIL import Image

load_dotenv()

VISION_MODEL = "qwen/qwen3.8-27b"
WASTE_TYPES = [
    "plastic", "organic", "paper", "glass", "metal", "textile",
    "construction_debris", "e_waste", "medical", "mixed", "other",
]
HAZARDS = [
    "medical_waste", "chemical_containers", "e_waste", "burning",
    "sewage_or_stagnant_water", "sharp_objects", "animal_carcass",
]
VOLUMES = ["small", "medium", "large"]
HAZARD_LEVELS = ["none_seen", "possible", "likely"]
CONFIDENCE = ["low", "medium", "high"]

PROMPT = """You are helping a municipal officer in Delhi triage a photo of street garbage.
Describe only what is visible. Do not guess at chemical toxicity. If you are unsure,
say so and lower your confidence.

Reply with ONLY a JSON object, with exactly these keys:
{
  "waste_types": a list with one or more of: plastic, organic, paper, glass, metal, textile, construction_debris, e_waste, medical, mixed, other,
  "volume": one of: small, medium, large,
  "hazard_indicators": a list with zero or more of: medical_waste, chemical_containers, e_waste, burning, sewage_or_stagnant_water, sharp_objects, animal_carcass,
  "hazard_level": one of: none_seen, possible, likely,
  "hazard_reason": "one short sentence, or an empty string if none seen",
  "confidence": one of: low, medium, high,
  "summary": "one plain sentence describing the scene"
}"""


def _prepare(photo_path):
    img = Image.open(photo_path).convert("RGB")
    img.thumbnail((1024, 1024))
    buf = io.BytesIO()
    img.save(buf, "JPEG", quality=80)
    return base64.b64encode(buf.getvalue()).decode()


def _extract_json(text):
    text = re.sub(r"<think>.*?</think>", "", text or "", flags=re.S)
    start, end = text.find("{"), text.rfind("}")
    if start == -1 or end == -1:
        raise ValueError("The model did not return JSON")
    return json.loads(text[start : end + 1])


def _as_list(value):
    return value if isinstance(value, list) else []


def _clean(raw):
    if not isinstance(raw, dict):
        raise ValueError("Unexpected response format")
    types = [t for t in _as_list(raw.get("waste_types")) if t in WASTE_TYPES] or ["mixed"]
    hazards = [h for h in _as_list(raw.get("hazard_indicators")) if h in HAZARDS]
    level = raw.get("hazard_level")
    if level not in HAZARD_LEVELS:
        level = "possible" if hazards else "none_seen"
    if hazards and level == "none_seen":
        level = "possible"
    return {
        "waste_types": types,
        "volume": raw.get("volume") if raw.get("volume") in VOLUMES else "medium",
        "hazard_indicators": hazards,
        "hazard_level": level,
        "hazard_reason": str(raw.get("hazard_reason") or "")[:200],
        "confidence": raw.get("confidence") if raw.get("confidence") in CONFIDENCE else "low",
        "summary": str(raw.get("summary") or "")[:300],
    }


def analyze_waste(photo_path):
    # Returns a cleaned dict, or {"error": "..."} if anything goes wrong
    try:
        image_b64 = _prepare(photo_path)
        client = Groq(api_key=os.getenv("GROQ_API_KEY"))
        response = client.chat.completions.create(
            model=VISION_MODEL,
            messages=[
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": PROMPT},
                        {
                            "type": "image_url",
                            "image_url": {"url": f"data:image/jpeg;base64,{image_b64}"},
                        },
                    ],
                }
            ],
            temperature=0.2,
            max_completion_tokens=2048,
            response_format={"type": "json_object"},
        )
        return _clean(_extract_json(response.choices[0].message.content))
    except Exception as e:
        return {"error": str(e)[:200]}


if __name__ == "__main__":
    import sys

    path = sys.argv[1] if len(sys.argv) > 1 else "test.jpg"
    print(json.dumps(analyze_waste(path), indent=2))