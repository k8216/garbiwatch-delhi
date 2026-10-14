import json

import pandas as pd

from tools import _load, compute_severity

RED = "#e74c3c"
YELLOW = "#f1c40f"
GREEN = "#2ecc71"


def load_flags():
    try:
        with open("flags.json") as f:
            return json.load(f)
    except FileNotFoundError:
        return []


def pin_style(status, flagged):
    # Red = the agent flagged it or it is a hotspot, green = resolved, yellow = watch
    if flagged or status in ("new_hotspot", "chronic_hotspot"):
        return RED, "Action required"
    if status in ("resolved", "clean"):
        return GREEN, "Resolved"
    return YELLOW, "Under watch"


def location_statuses():
    flagged_names = {f["location"] for f in load_flags()}
    rows = []
    for loc in _load():
        severity = compute_severity(loc["name"])
        color, label = pin_style(severity["status"], loc["name"] in flagged_names)
        rows.append(
            {
                "name": loc["name"],
                "lat": loc["lat"],
                "lon": loc["lon"],
                "status": severity["status"],
                "priority": severity["priority"],
                "latest_coverage": severity["latest_coverage"],
                "change": severity["change_since_first_reading"],
                "readings": len(loc["history"]),
                "color": color,
                "label": label,
            }
        )
    return rows


def history_frame():
    rows = []
    for loc in _load():
        for reading in loc["history"]:
            rows.append(
                {
                    "date": reading["date"],
                    "location": loc["name"],
                    "coverage": reading["coverage"],
                }
            )
    frame = pd.DataFrame(rows)
    return frame.pivot_table(
        index="date", columns="location", values="coverage", aggfunc="last"
    ).sort_index()