import json
import os
import random
from datetime import date, datetime, timedelta

from PIL import Image, ImageEnhance

from advice import build_advice, effective_priority
from complaints import UPLOAD_DIR, _save, reset_complaints
from tools import compute_severity

DEMO_MARKER = ".demo_loaded_v2"
DEMO_PHOTO = "demo_photo.jpg"

PATTERNS = {
    "worsening": [0.08, 0.12, 0.20, 0.30, 0.42, 0.55],
    "chronic": [0.58, 0.60, 0.62, 0.60, 0.63, 0.61],
    "new_hotspot": [0.00, 0.00, 0.02, 0.10, 0.35, 0.68],
    "resolved": [0.50, 0.42, 0.30, 0.15, 0.04, 0.00],
    "improving": [0.50, 0.45, 0.38, 0.30, 0.25, 0.20],
    "stable_low": [0.12, 0.10, 0.14, 0.11, 0.13, 0.12],
    "clean": [0.02, 0.00, 0.03, 0.00, 0.01, 0.00],
}

# name, latitude, longitude (approximate), pattern. All readings are simulated.
LOCATION_SEEDS = [
    ("Dwarka Sector 10 Market", 28.5823, 77.0500, "worsening"),
    ("Najafgarh Road Roadside", 28.6180, 77.0200, "chronic"),
    ("Sector 21 Metro Station", 28.5521, 77.0580, "resolved"),
    ("Palam Vihar Nala Side", 28.5950, 77.0900, "stable_low"),
    ("Uttam Nagar Main Road", 28.6190, 77.0550, "new_hotspot"),
    ("Janakpuri C-1 Market", 28.6219, 77.0878, "chronic"),
    ("Vikaspuri Outer Ring Road", 28.6420, 77.0680, "improving"),
    ("Tilak Nagar Market", 28.6393, 77.0960, "worsening"),
    ("Rajouri Garden Flyover", 28.6492, 77.1220, "new_hotspot"),
    ("Punjabi Bagh Park Side", 28.6683, 77.1317, "stable_low"),
    ("Paschim Vihar Main Road", 28.6700, 77.1000, "clean"),
    ("Mahavir Enclave Lane", 28.6100, 77.0700, "resolved"),
    ("Palam Colony Market", 28.5880, 77.0830, "improving"),
    ("Bijwasan Road Junction", 28.5450, 77.0450, "stable_low"),
]


def _ai(types, volume, hazards, level, reason, confidence, summary):
    return {
        "waste_types": types, "volume": volume, "hazard_indicators": hazards,
        "hazard_level": level, "hazard_reason": reason,
        "confidence": confidence, "summary": summary,
    }


# id, location, note, status, hours ago, detection (count, confidence, coverage), ai, remarks, flagged, agent summary
COMPLAINT_SEEDS = [
    ("DEMO-01", "Najafgarh Road Roadside", "Huge pile along the service road, it smells bad.", "In review", 52,
     (3, 0.58, 0.61), _ai(["mixed", "plastic"], "large", [], "none_seen", "", "medium",
                          "A long roadside pile of mixed plastic and household waste."),
     ["Accepted by the officer. Inspection planned."], True,
     "Najafgarh Road Roadside is a chronic hotspot: coverage has stayed near 0.6 for six weeks. I flagged it for reinspection."),
    ("DEMO-02", "Uttam Nagar Main Road", "A new dump appeared near the market this week.", "New", 5,
     (4, 0.52, 0.70), _ai(["mixed", "organic"], "large", [], "none_seen", "", "medium",
                          "A large new heap of mixed and wet waste beside the road."),
     [], False, ""),
    ("DEMO-03", "Dwarka Sector 10 Market", "Garbage keeps piling up behind the shops.", "Assigned", 30,
     (2, 0.47, 0.34), _ai(["plastic", "organic"], "medium", [], "none_seen", "", "high",
                          "Plastic packaging and food waste behind a row of shops."),
     ["Accepted by the officer.", "Sanitation crew assigned for tomorrow morning."], True,
     "Dwarka Sector 10 Market is worsening: coverage rose from 0.08 to 0.55 in five weeks. I flagged it for reinspection."),
    ("DEMO-04", "Rajouri Garden Flyover", "Found bags that look like medical waste near the pillar.", "New", 3,
     (2, 0.44, 0.28), _ai(["medical", "mixed"], "small", ["medical_waste", "sharp_objects"], "likely",
                          "Red and yellow bags with what may be syringes are visible.", "medium",
                          "A small pile with coloured bags that resemble bio-medical waste."),
     [], False, ""),
    ("DEMO-05", "Tilak Nagar Market", "Waste is spilling onto the road after the weekend market.", "In review", 20,
     (2, 0.41, 0.33), _ai(["organic", "plastic"], "medium", [], "none_seen", "", "medium",
                          "Vegetable waste and plastic bags spread along the kerb."),
     ["Accepted by the officer."], True,
     "Tilak Nagar Market is worsening, with coverage rising steadily. I flagged it for reinspection."),
    ("DEMO-06", "Sector 21 Metro Station", "Rubbish near the station exit.", "Resolved", 120,
     (1, 0.39, 0.20), _ai(["plastic", "paper"], "small", [], "none_seen", "", "high",
                          "A small scatter of plastic and paper near an exit."),
     ["Accepted by the officer.", "Crew cleared the area. Verified clean."], False,
     "Sector 21 Metro Station has improved from 0.40 to 0.00 coverage. No reinspection is needed."),
    ("DEMO-07", "Bijwasan Road Junction", "Builders dumped rubble on the roadside.", "Assigned", 40,
     (2, 0.49, 0.30), _ai(["construction_debris"], "medium", [], "none_seen", "", "high",
                          "Bricks, broken concrete and sand dumped at a junction."),
     ["Accepted by the officer.", "Loader and tipper requested."], False,
     "Bijwasan Road Junction is stable at a low level, but the debris needs heavy equipment. No flag needed."),
    ("DEMO-08", "Mahavir Enclave Lane", "Cleared now, thank you.", "Resolved", 200,
     (1, 0.36, 0.15), _ai(["plastic"], "small", [], "none_seen", "", "medium",
                          "A few scattered plastic items on a lane."),
     ["Accepted by the officer.", "Cleared during the routine round."], False,
     "Mahavir Enclave Lane has improved to zero coverage. No reinspection is needed."),
    ("DEMO-09", "Janakpuri C-1 Market", "Photo of the empty street.", "Rejected", 70,
     (0, 0.0, 0.0), _ai(["other"], "small", [], "none_seen", "", "low",
                        "No garbage is visible in this photo."),
     ["Rejected: the photo does not show garbage."], False, ""),
]

FORMAT = "%d %b %Y, %H:%M"


def _history(name, pattern):
    rng = random.Random(name)
    today = date.today()
    history = []
    for i, base in enumerate(PATTERNS[pattern]):
        coverage = max(0.0, round(base + rng.uniform(-0.02, 0.02), 2))
        history.append(
            {
                "date": str(today - timedelta(weeks=5 - i)),
                "count": round(coverage * 6),
                "coverage": coverage,
            }
        )
    return history


def _demo_photo(cid, index):
    if not os.path.exists(DEMO_PHOTO):
        return ""
    img = Image.open(DEMO_PHOTO).convert("RGB")
    if index % 2:
        img = img.transpose(Image.FLIP_LEFT_RIGHT)
    w, h = img.size
    rng = random.Random(cid)
    keep = rng.uniform(0.75, 0.95)
    left = rng.randint(0, int(w * (1 - keep)))
    top = rng.randint(0, int(h * (1 - keep)))
    img = img.crop((left, top, left + int(w * keep), top + int(h * keep)))
    img = ImageEnhance.Brightness(img).enhance(rng.uniform(0.9, 1.1))
    img.thumbnail((1280, 1280))
    os.makedirs(UPLOAD_DIR, exist_ok=True)
    path = f"{UPLOAD_DIR}/{cid}.jpg"
    img.save(path, quality=85)
    return path


def _seed_complaints():
    now = datetime.now()
    complaints, flags = [], []
    for index, seed in enumerate(COMPLAINT_SEEDS):
        cid, location, note, status, hours, det, ai, remarks, flagged, summary = seed
        count, confidence, coverage = det
        severity = compute_severity(location, extra_coverage=coverage)
        if count == 0:
            priority = "unverified"
        elif severity["priority"] == "none":
            priority = "low"
        else:
            priority = severity["priority"]
        priority = effective_priority(priority, ai)

        created = now - timedelta(hours=hours)
        timeline = [{"time": created.strftime(FORMAT), "text": "Complaint received"}]
        for step, remark in enumerate(remarks, start=1):
            when = created + timedelta(hours=step * 2)
            text = remark if remark.startswith("Rejected") else f"Status updated: {remark}"
            timeline.append({"time": when.strftime(FORMAT), "text": text})

        photo = _demo_photo(cid, index)
        complaints.append(
            {
                "id": cid,
                "ts": created.timestamp(),
                "created": created.strftime(FORMAT),
                "location": location,
                "note": note,
                "photo": photo,
                "photo_boxes": photo,
                "detection": {"count": count, "max_confidence": confidence, "coverage": coverage},
                "severity": severity,
                "priority": priority,
                "status": status,
                "agent_summary": summary,
                "agent_flagged": flagged,
                "timeline": timeline,
                "ai": ai,
                "advice": build_advice(ai, priority),
                "demo": True,
            }
        )
        if flagged:
            flags.append(
                {"location": location, "reason": summary, "date": str(created.date())}
            )

    _save(complaints)
    if flags:
        with open("flags.json", "w") as f:
            json.dump(flags, f, indent=2)


def reset_demo():
    locations = [
        {"name": n, "lat": la, "lon": lo, "history": _history(n, p)}
        for n, la, lo, p in LOCATION_SEEDS
    ]
    with open("locations.json", "w") as f:
        json.dump({"locations": locations}, f, indent=2)
    if os.path.exists("flags.json"):
        os.remove("flags.json")
    reset_complaints()
    _seed_complaints()
    with open(DEMO_MARKER, "w") as f:
        f.write("ok")


def ensure_demo_data():
    if not os.path.exists(DEMO_MARKER):
        reset_demo()