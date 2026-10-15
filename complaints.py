import io
import json
import os
import secrets
import shutil
import time
from datetime import datetime

from PIL import Image

COMPLAINTS_FILE = "complaints.json"
UPLOAD_DIR = "uploads"
STATUSES = ["New", "In review", "Assigned", "Resolved", "Rejected"]
PRIORITY_RANK = {"high": 0, "medium": 1, "low": 2, "unverified": 3}


def _now():
    try:
        from zoneinfo import ZoneInfo

        return datetime.now(ZoneInfo("Asia/Kolkata")).strftime("%d %b %Y, %H:%M")
    except Exception:
        return datetime.now().strftime("%d %b %Y, %H:%M")


def all_complaints():
    try:
        with open(COMPLAINTS_FILE) as f:
            return json.load(f)
    except FileNotFoundError:
        return []


def _save(complaints):
    with open(COMPLAINTS_FILE, "w") as f:
        json.dump(complaints, f, indent=2)


def get_complaint(complaint_id):
    wanted = complaint_id.strip().upper()
    for c in all_complaints():
        if c["id"] == wanted:
            return c
    return None


def create_complaint(location, note, photo_bytes, annotated, numbers, severity):
    complaints = all_complaints()
    existing = {c["id"] for c in complaints}
    cid = "GW-" + secrets.token_hex(3).upper()
    while cid in existing:
        cid = "GW-" + secrets.token_hex(3).upper()

    os.makedirs(UPLOAD_DIR, exist_ok=True)
    photo_path = f"{UPLOAD_DIR}/{cid}.jpg"
    boxes_path = f"{UPLOAD_DIR}/{cid}_boxes.jpg"

    photo = Image.open(io.BytesIO(photo_bytes)).convert("RGB")
    photo.thumbnail((1280, 1280))
    photo.save(photo_path, quality=85)
    Image.fromarray(annotated).save(boxes_path, quality=85)

    if numbers["count"] == 0:
        priority = "unverified"
    elif severity["priority"] == "none":
        priority = "low"
    else:
        priority = severity["priority"]

    complaint = {
        "id": cid,
        "ts": time.time(),
        "created": _now(),
        "location": location,
        "note": note.strip(),
        "photo": photo_path,
        "photo_boxes": boxes_path,
        "detection": numbers,
        "severity": severity,
        "priority": priority,
        "status": "New",
        "agent_summary": "",
        "agent_flagged": False,
        "timeline": [{"time": _now(), "text": "Complaint received"}],
    }
    complaints.append(complaint)
    _save(complaints)
    return complaint


def update_status(complaint_id, status, remark=""):
    complaints = all_complaints()
    for c in complaints:
        if c["id"] == complaint_id:
            c["status"] = status
            text = f"Status changed to {status}"
            if remark.strip():
                text += f": {remark.strip()}"
            c["timeline"].append({"time": _now(), "text": text})
    _save(complaints)


def set_agent_result(complaint_id, summary, flagged):
    complaints = all_complaints()
    for c in complaints:
        if c["id"] == complaint_id:
            c["agent_summary"] = summary
            c["agent_flagged"] = flagged
    _save(complaints)


def sort_for_inbox(complaints):
    return sorted(
        complaints,
        key=lambda c: (PRIORITY_RANK.get(c["priority"], 9), -c["ts"]),
    )


def reset_complaints():
    if os.path.exists(COMPLAINTS_FILE):
        os.remove(COMPLAINTS_FILE)
    if os.path.isdir(UPLOAD_DIR):
        shutil.rmtree(UPLOAD_DIR)
        

def set_ai_result(complaint_id, ai, advice, priority):
    complaints = all_complaints()
    for c in complaints:
        if c["id"] == complaint_id:
            c["ai"] = ai
            c["advice"] = advice
            c["priority"] = priority
    _save(complaints)