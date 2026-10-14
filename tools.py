import json
from datetime import date

DATA_FILE = "locations.json"
FLAGS_FILE = "flags.json"


def _load():
    with open(DATA_FILE) as f:
        return json.load(f)["locations"]


def _find(name):
    for loc in _load():
        if loc["name"].lower() == name.lower():
            return loc
    return None


def get_area_history(location):
    loc = _find(location)
    if loc is None:
        return {"error": f"Unknown location: {location}"}
    return {"location": loc["name"], "history": loc["history"]}


def compute_severity(location, extra_coverage=None):
    loc = _find(location)
    if loc is None:
        return {"error": f"Unknown location: {location}"}

    cov = [r["coverage"] for r in loc["history"]]
    if extra_coverage is not None:
        cov.append(extra_coverage)  # a pending reading that is not saved yet
    first, latest = cov[0], cov[-1]
    change = round(latest - first, 2)

    if latest < 0.05:
        status = "resolved" if max(cov) >= 0.2 else "clean"
    elif first < 0.05 and latest >= 0.3:
        status = "new_hotspot"
    elif latest >= 0.5 and abs(change) <= 0.1:
        status = "chronic_hotspot"
    elif change >= 0.25 or (latest >= 0.5 and change > 0):
        status = "worsening"
    elif change <= -0.15:
        status = "improving"
    else:
        status = "stable_low"

    priority = {
        "new_hotspot": "high",
        "chronic_hotspot": "high",
        "worsening": "medium",
        "improving": "low",
        "stable_low": "low",
        "resolved": "none",
        "clean": "none",
    }[status]

    return {
        "location": loc["name"],
        "status": status,
        "priority": priority,
        "latest_coverage": latest,
        "change_since_first_reading": change,
    }


def flag_for_reinspection(location, reason):
    loc = _find(location)
    if loc is None:
        return {"error": f"Unknown location: {location}"}

    try:
        with open(FLAGS_FILE) as f:
            flags = json.load(f)
    except FileNotFoundError:
        flags = []

    flags.append({"location": loc["name"], "reason": reason, "date": str(date.today())})
    with open(FLAGS_FILE, "w") as f:
        json.dump(flags, f, indent=2)

    return {"flagged": loc["name"], "reason": reason}


def record_reading(location, count, coverage):
    with open(DATA_FILE) as f:
        data = json.load(f)

    for loc in data["locations"]:
        if loc["name"].lower() == location.lower():
            loc["history"].append(
                {"date": str(date.today()), "count": count, "coverage": coverage}
            )
            break

    with open(DATA_FILE, "w") as f:
        json.dump(data, f, indent=2)