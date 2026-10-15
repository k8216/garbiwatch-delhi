DRY = {
    "equipment": ["Gloves", "Brooms and grabber tools", "Heavy-duty bin bags"],
    "approach": "Sweep and bag the dry litter. Set aside recyclables if a collection point is nearby.",
}
SHARP = {
    "equipment": ["Puncture-resistant gloves", "Closed boots", "Dustpan, brush and a rigid container"],
    "approach": "Pick up broken glass and metal by hand with protection. Do not put loose sharp items in thin bags.",
}
MIXED = {
    "equipment": ["Gloves and masks", "Shovels and rakes", "Bin bags and bins", "Tipper or compactor vehicle"],
    "approach": "Remove sharp or hazardous items first, then load the bulk waste and sweep the area.",
}

WASTE_PLAYBOOK = {
    "plastic": DRY,
    "paper": DRY,
    "textile": DRY,
    "glass": SHARP,
    "metal": SHARP,
    "organic": {
        "equipment": ["Gloves and masks", "Shovels", "Lidded bins or a covered vehicle", "Disinfectant for the spot"],
        "approach": "Remove wet waste quickly because it attracts pests and smells. Clean and disinfect the spot afterwards.",
    },
    "construction_debris": {
        "equipment": ["Loader or JCB", "Tipper truck", "Dust masks", "Barricades or cones"],
        "approach": "Use machinery for heavy debris and take it to an authorised construction-waste site. Keep the road clear while loading.",
    },
    "e_waste": {
        "equipment": ["Gloves", "A separate covered container"],
        "approach": "Keep electronics apart from other waste and hand them to an authorised e-waste collector.",
    },
    "medical": {
        "equipment": [],
        "approach": "",
    },
    "mixed": MIXED,
    "other": MIXED,
}

HAZARD_PLAYBOOK = {
    "medical_waste": {
        "team": "Authorised bio-medical waste handlers",
        "equipment": ["Full protective gear (gloves, mask, apron)", "Sharps container", "Bio-medical waste bags"],
        "note": "Do not hand-sort. Keep people away from the spot until trained handlers arrive.",
    },
    "chemical_containers": {
        "team": "Hazardous-waste team or the pollution control authority",
        "equipment": ["Chemical-resistant gloves", "Respirator mask", "Sealed containers"],
        "note": "Do not open, burn or mix the containers. Keep people away and call the specialist team.",
    },
    "e_waste": {
        "team": "Authorised e-waste collector",
        "equipment": ["Gloves", "Separate covered container"],
        "note": "Keep batteries and electronics out of general waste.",
    },
    "burning": {
        "team": "Fire service and the pollution control authority",
        "equipment": ["Fire safety equipment (fire service)"],
        "note": "Do not approach burning waste. Call the fire service first.",
    },
    "sewage_or_stagnant_water": {
        "team": "Drainage and sanitation department",
        "equipment": ["Waterproof boots and gloves", "Suction or pumping equipment"],
        "note": "Wear waterproof protection and avoid direct contact with the water.",
    },
    "sharp_objects": {
        "team": "Crew trained in handling sharps",
        "equipment": ["Puncture-resistant gloves", "Sharps container"],
        "note": "Pick up sharp items with tongs or protected hands only.",
    },
    "animal_carcass": {
        "team": "Veterinary or carcass removal service",
        "equipment": ["Gloves and masks", "Sealed bags", "Disinfectant"],
        "note": "Do not handle without protection. Disinfect the spot afterwards.",
    },
}

VEHICLE = {
    "small": "Handcart or two-wheeler carrier",
    "medium": "Light vehicle such as a mini tipper",
    "large": "Tipper truck, plus a loader if the pile is heavy or compacted",
}


def effective_priority(priority, ai):
    level = ai.get("hazard_level")
    if level == "likely":
        return "high"
    if level == "possible" and priority in ("low", "unverified"):
        return "medium"
    return priority


def _response_target(priority, level):
    if level == "likely":
        return "same day, after a safety check"
    if level == "possible":
        return "within 24 hours, after a safety check"
    targets = {
        "high": "within 24 hours",
        "medium": "within 3 days",
        "low": "routine round, within a week",
    }
    return targets.get(priority, "after a human check")


def build_advice(ai, priority):
    types = ai.get("waste_types") or ["mixed"]
    hazards = list(ai.get("hazard_indicators", []))
    if "medical" in types and "medical_waste" not in hazards:
        hazards.append("medical_waste")
    if "e_waste" in types and "e_waste" not in hazards:
        hazards.append("e_waste")

    equipment, approach = [], []
    for t in types:
        step = WASTE_PLAYBOOK.get(t, WASTE_PLAYBOOK["other"])
        for item in step["equipment"]:
            if item not in equipment:
                equipment.append(item)
        if step["approach"] and step["approach"] not in approach:
            approach.append(step["approach"])

    teams, notes, special_equipment = [], [], []
    for h in hazards:
        rule = HAZARD_PLAYBOOK[h]
        if rule["team"] not in teams:
            teams.append(rule["team"])
        notes.append(rule["note"])
        for item in rule["equipment"]:
            if item not in special_equipment:
                special_equipment.append(item)

    if hazards:
        approach.insert(
            0, "Hold the ordinary clean-up crew until the specialist team has made the area safe."
        )

    level = ai.get("hazard_level", "none_seen")
    if hazards and level == "none_seen":
        level = "possible"

    return {
        "equipment": equipment,
        "approach": approach,
        "vehicle": VEHICLE.get(ai.get("volume"), VEHICLE["medium"]),
        "specialist_teams": teams,
        "specialist_equipment": special_equipment,
        "safety_notes": notes,
        "hold_ordinary_crew": bool(hazards),
        "response_target": _response_target(priority, level if hazards else "none_seen"),
    }


def draft_letter(c):
    d = c["detection"]
    ai = c.get("ai") or {}
    advice = c.get("advice") or {}
    lines = [
        "DRAFT. Not sent to any authority.",
        "",
        "To: The Zonal Deputy Commissioner, Municipal Corporation of Delhi",
        f"Subject: Garbage accumulation at {c['location']} (reference {c['id']})",
        "",
        "Sir/Madam,",
        "",
        f"A report received on {c['created']} shows garbage accumulation at {c['location']}.",
        f"The AI detector found {d['count']} garbage region(s), covering about "
        f"{round(d['coverage'] * 100)}% of the photo.",
    ]
    if c["note"]:
        lines.append(f"The citizen added: {c['note']}")
    if ai and "error" not in ai:
        lines.append(
            "The waste appears to be: " + ", ".join(t.replace("_", " ") for t in ai["waste_types"])
            + f" (volume: {ai['volume']}, AI confidence: {ai['confidence']})."
        )
        if ai["hazard_level"] != "none_seen":
            lines.append(
                f"A {ai['hazard_level']} hazard was noted. {ai['hazard_reason']} "
                "This is an AI estimate from a photo and needs checking on site."
            )
    if advice:
        lines.append("Suggested equipment: " + ", ".join(advice["equipment"] + advice["specialist_equipment"]) + ".")
        lines.append(f"Suggested response: {advice['response_target']}.")
    lines += [
        "",
        "We request that the area be inspected and cleared.",
        "",
        "Regards,",
        "GarbiWatch Delhi (prototype)",
    ]
    return "\n".join(lines)