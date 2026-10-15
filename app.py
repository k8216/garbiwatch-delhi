import hmac
import os
import tempfile

import altair as alt
import pandas as pd
import streamlit as st

try:
    os.environ["GROQ_API_KEY"] = st.secrets["GROQ_API_KEY"]
except Exception:
    pass
try:
    os.environ["ADMIN_PASSWORD"] = st.secrets["ADMIN_PASSWORD"]
except Exception:
    pass

from advice import build_advice, draft_letter, effective_priority
from agent import run_agent
from complaints import (
    STATUSES,
    all_complaints,
    create_complaint,
    get_complaint,
    set_agent_result,
    set_ai_result,
    sort_for_inbox,
    update_status,
)
from dashboard import GREEN, RED, YELLOW, history_frame, load_flags, location_statuses
from detect import analyze
from heatmap import build_map
from seed import ensure_demo_data, reset_demo
from tools import compute_severity, record_reading
from vision import analyze_waste

MAP_STYLE = "street"  # change to "dark" to try the dark base map
STATUS_LABELS = ["Action required", "Under watch", "Resolved"]
PRIORITY_ICON = {"high": "🔴", "medium": "🟠", "low": "🟡", "unverified": "⚪"}
MAX_REPORTS_PER_VISIT = 3

st.set_page_config(page_title="GarbiWatch Delhi", page_icon="🗑️", layout="wide")

if "role" not in st.session_state:
    st.session_state["role"] = None
if "upload_nonce" not in st.session_state:
    st.session_state["upload_nonce"] = 0

ensure_demo_data()
locs = location_statuses()
flags = load_flags()
names = [loc["name"] for loc in locs]


@st.cache_data(show_spinner="Looking for garbage in your photo...")
def analyze_photo(photo_bytes):
    with tempfile.NamedTemporaryFile(delete=False, suffix=".jpg") as tmp:
        tmp.write(photo_bytes)
        path = tmp.name
    try:
        return analyze(path)
    finally:
        os.remove(path)


def run_ai_analysis(complaint_id):
    c = get_complaint(complaint_id)
    ai = analyze_waste(c["photo"])
    if "error" in ai:
        set_ai_result(c["id"], ai, None, c["priority"])
        return
    priority = effective_priority(c["priority"], ai)
    set_ai_result(c["id"], ai, build_advice(ai, priority), priority)


def accept_complaint(c, remark):
    # The officer verifies the report: save the reading, then let the agent investigate
    record_reading(c["location"], c["detection"]["count"], c["detection"]["coverage"])
    update_status(c["id"], "In review", remark)
    detection = {"count": c["detection"]["count"], "coverage": c["detection"]["coverage"]}
    try:
        answer, trace = run_agent(c["location"], detection)
        flagged = any(s["tool"] == "flag_for_reinspection" for s in trace)
        set_agent_result(c["id"], answer, flagged)
    except Exception:
        set_agent_result(c["id"], "The AI agent was unavailable. Please review this one manually.", False)


def show_ai_report(c):
    ai = c.get("ai")
    if not ai:
        st.info("No AI waste analysis yet.")
        return
    if "error" in ai:
        st.warning("The AI waste analysis was unavailable for this photo. Use the button below to retry.")
        return

    st.markdown("**AI waste analysis**")
    types = ", ".join(t.replace("_", " ") for t in ai["waste_types"])
    st.markdown(f"Waste: **{types}** · Volume: **{ai['volume']}** · Confidence: **{ai['confidence']}**")
    st.write(ai["summary"])
    if ai["hazard_level"] != "none_seen":
        hazards = ", ".join(h.replace("_", " ") for h in ai["hazard_indicators"]) or "see reason"
        st.error(
            f"☣️ {ai['hazard_level'].title()} hazard ({hazards}). {ai['hazard_reason']} "
            "This is an AI estimate from a photo. Verify on site before sending an ordinary crew."
        )

    advice = c.get("advice")
    if advice:
        st.markdown("**Suggested approach**")
        if advice["hold_ordinary_crew"]:
            st.markdown("Send first: " + ", ".join(advice["specialist_teams"]))
            st.markdown("Specialist equipment: " + ", ".join(advice["specialist_equipment"]))
        st.markdown("Equipment for the clean-up crew: " + ", ".join(advice["equipment"]))
        st.markdown(f"Vehicle: {advice['vehicle']}")
        st.markdown(f"Response target: **{advice['response_target']}**")
        for step in advice["approach"]:
            st.markdown(f"- {step}")
        for note in advice["safety_notes"]:
            st.markdown(f"- ⚠️ {note}")
        st.caption("General guidance, not an official MCD procedure. Check it against local rules.")


# ---------------- Landing page ----------------
def landing_view():
    st.markdown(
        "<style>[data-testid='stSidebar'], [data-testid='stSidebarCollapsedControl'] "
        "{display: none;}</style>",
        unsafe_allow_html=True,
    )
    complaints = all_complaints()

    st.title("GarbiWatch Delhi")
    st.subheader("Report garbage. Let AI triage it. Help the municipal team act faster.")

    m1, m2, m3, m4 = st.columns(4)
    m1.metric("Areas monitored", len(locs))
    m2.metric("Reports received", len(complaints))
    m3.metric("Resolved", sum(1 for c in complaints if c["status"] == "Resolved"))
    m4.metric("Areas needing action", sum(1 for loc in locs if loc["label"] == "Action required"))

    st.divider()
    left, right = st.columns(2)
    with left:
        with st.container(border=True):
            st.markdown("### 🧑 Citizen")
            st.write("Report garbage with a photo and track what happens next. No account needed.")
            st.caption("Try tracking the sample report DEMO-01 after you continue.")
            if st.button("Continue as citizen", key="go_citizen"):
                st.session_state["role"] = "citizen"
                st.rerun()
    with right:
        with st.container(border=True):
            st.markdown("### 🏛️ MCD officer")
            st.write("Review reports, see the AI's findings and suggestions, and act on them.")
            password = st.text_input("Officer password", type="password", key="landing_pw")
            if st.button("Log in", key="go_admin"):
                expected = os.getenv("ADMIN_PASSWORD")
                if not expected:
                    st.error("No officer password is set on the server.")
                elif hmac.compare_digest(password.encode(), expected.encode()):
                    st.session_state["role"] = "admin"
                    st.rerun()
                else:
                    st.error("Wrong password.")

    st.divider()
    st.markdown("### How it works")
    s1, s2, s3 = st.columns(3)
    s1.markdown("**1. Report**  \nUpload a photo of the garbage and choose the area.")
    s2.markdown(
        "**2. AI checks**  \nA trained detector finds the garbage. A vision model describes "
        "the waste type and any visible hazard."
    )
    s3.markdown(
        "**3. Officer acts**  \nThe officer sees severity, suggested equipment and approach, "
        "then decides what to do."
    )
    st.caption(
        "Prototype built for a college AI project. Demo data is simulated, and reports go to "
        "this app's officer page, not to the real MCD."
    )


# ---------------- Citizen site ----------------
def public_view():
    st.title("GarbiWatch Delhi")
    st.caption("Report garbage in your area. An AI checks your photo and the municipal team follows up.")

    tab_report, tab_track, tab_map = st.tabs(["Report garbage", "Track my complaint", "City map and areas"])

    with tab_report:
        st.subheader("Report garbage near you")
        st.caption(
            "Prototype: complaints go to this app's officer page, not to the real MCD. "
            "Please avoid photographing people's faces or number plates. Stay away from medical, "
            "chemical or burning waste."
        )

        if "submitted_id" in st.session_state:
            st.success(
                f"Complaint submitted. Your complaint ID is **{st.session_state['submitted_id']}**. "
                "Keep it to track progress in the next tab."
            )

        limit_reached = st.session_state.get("submit_count", 0) >= MAX_REPORTS_PER_VISIT
        if limit_reached:
            st.warning(f"Demo limit reached: {MAX_REPORTS_PER_VISIT} reports per visit.")

        location = st.selectbox("Area", names)
        note = st.text_area("Anything we should know? (optional)", max_chars=300)
        uploaded = st.file_uploader(
            "Street photo",
            type=["jpg", "jpeg", "png"],
            key=f"photo_{st.session_state['upload_nonce']}",
        )

        if uploaded is not None:
            photo_bytes = uploaded.getvalue()
            numbers, annotated = analyze_photo(photo_bytes)
            st.image(annotated, caption="What the AI detected", channels="RGB")

            if numbers["count"] == 0:
                st.warning(
                    "The AI could not find garbage in this photo. You can still submit it, "
                    "and an officer will review it."
                )
            else:
                st.write(
                    f"Garbage regions found: **{numbers['count']}**, "
                    f"covering about **{round(numbers['coverage'] * 100)}%** of the photo."
                )

            if st.button("Submit complaint", disabled=limit_reached):
                with st.spinner("Submitting and analysing your photo..."):
                    severity = compute_severity(location, extra_coverage=numbers["coverage"])
                    complaint = create_complaint(location, note, photo_bytes, annotated, numbers, severity)
                    run_ai_analysis(complaint["id"])
                st.session_state["submitted_id"] = complaint["id"]
                st.session_state["submit_count"] = st.session_state.get("submit_count", 0) + 1
                st.session_state["upload_nonce"] += 1
                st.rerun()

    with tab_track:
        st.subheader("Track my complaint")
        cid = st.text_input(
            "Complaint ID",
            value=st.session_state.get("submitted_id", ""),
            placeholder="GW-1A2B3C",
        )
        if cid:
            c = get_complaint(cid)
            if c is None:
                st.error("No complaint found with that ID.")
            else:
                st.markdown(f"**{c['id']}** · {c['location']}")
                st.markdown(f"Status: **{c['status']}**")
                if c["photo"] and os.path.exists(c["photo"]):
                    st.image(c["photo"], width=300)
                for event in c["timeline"]:
                    st.markdown(f"- {event['time']}: {event['text']}")

    with tab_map:
        st.subheader("City map")
        colors = {loc["name"]: loc["color"] for loc in locs}
        st.iframe(build_map(style=MAP_STYLE, status_colors=colors).get_root().render(), height=520)
        st.caption("🔴 Action required   🟡 Under watch   🟢 Resolved")

        left, right = st.columns(2)
        with left:
            st.subheader("Areas needing attention")
            ranked = sorted(locs, key=lambda loc: loc["latest_coverage"], reverse=True)[:5]
            st.dataframe(
                pd.DataFrame(
                    [
                        {
                            "Area": loc["name"],
                            "Score (0-100)": round(loc["latest_coverage"] * 100),
                            "Status": loc["label"],
                        }
                        for loc in ranked
                    ]
                ),
                hide_index=True,
            )
        with right:
            st.subheader("Recently resolved")
            resolved = [c for c in all_complaints() if c["status"] == "Resolved"][:5]
            if resolved:
                for c in resolved:
                    st.markdown(f"✅ **{c['location']}** ({c['id']}, {c['created']})")
            else:
                st.write("Nothing resolved yet.")


# ---------------- Officer site ----------------
def admin_view():
    st.title("GarbiWatch Delhi: MCD officer")
    st.caption("Review citizen reports, check the AI's findings, and act on them.")

    tab_inbox, tab_overview, tab_hot = st.tabs(["Complaint inbox", "Overview", "Hotspots & Analytics"])

    with tab_inbox:
        complaints = all_complaints()
        m1, m2, m3, m4 = st.columns(4)
        m1.metric("Total complaints", len(complaints))
        m2.metric("New", sum(1 for c in complaints if c["status"] == "New"))
        m3.metric("Open", sum(1 for c in complaints if c["status"] in ("In review", "Assigned")))
        m4.metric("Resolved", sum(1 for c in complaints if c["status"] == "Resolved"))

        show = st.multiselect("Show statuses", STATUSES, default=["New", "In review", "Assigned"])
        shown = sort_for_inbox([c for c in complaints if c["status"] in show])

        if not complaints:
            st.info("No complaints yet. Go back to the start page, continue as a citizen and submit one.")
        elif not shown:
            st.write("Nothing matches this filter.")

        for c in shown:
            icon = PRIORITY_ICON.get(c["priority"], "⚪")
            ai = c.get("ai") or {}
            hazard_mark = " ☣️" if ai.get("hazard_level") in ("possible", "likely") else ""
            demo_mark = " (demo)" if c.get("demo") else ""
            label = (
                f"{icon} {c['id']}{demo_mark} · {c['location']} · "
                f"{c['priority']} priority · {c['status']}{hazard_mark}"
            )
            with st.expander(label):
                left, right = st.columns(2)
                with left:
                    if c["photo_boxes"] and os.path.exists(c["photo_boxes"]):
                        caption = "Sample photo" if c.get("demo") else "AI detection"
                        st.image(c["photo_boxes"], caption=caption)
                    d = c["detection"]
                    sev = c["severity"]
                    st.markdown(f"**Submitted:** {c['created']}")
                    st.markdown(f"**Area:** {c['location']}")
                    st.markdown(f"**Citizen's note:** {c['note'] or 'none'}")
                    st.markdown(
                        f"**Detector:** {d['count']} region(s), top confidence "
                        f"{d['max_confidence']}, covering {round(d['coverage'] * 100)}% of the photo"
                    )
                    st.markdown(
                        f"**Trend if accepted:** {sev['status'].replace('_', ' ')} "
                        f"({sev['priority']} priority, {sev['change_since_first_reading']:+.2f} "
                        "since the first reading)"
                    )
                with right:
                    show_ai_report(c)
                    if c["agent_summary"]:
                        st.markdown("**AI agent's review**")
                        st.write(c["agent_summary"])
                        if c["agent_flagged"]:
                            st.error("Flagged for reinspection")

                st.markdown("**Timeline**")
                for event in c["timeline"]:
                    st.markdown(f"- {event['time']}: {event['text']}")

                if not c.get("ai") or "error" in c["ai"]:
                    if st.button("Run AI analysis", key=f"ai_{c['id']}"):
                        with st.spinner("Analysing the photo..."):
                            run_ai_analysis(c["id"])
                        st.rerun()

                remark = st.text_input(
                    "Remark (the citizen can see this)", key=f"remark_{c['id']}"
                )
                if c["status"] == "New":
                    b1, b2 = st.columns(2)
                    if b1.button("Accept and run AI agent", key=f"accept_{c['id']}"):
                        with st.spinner("Saving the reading and running the agent..."):
                            accept_complaint(c, remark)
                        st.rerun()
                    if b2.button("Reject", key=f"reject_{c['id']}"):
                        update_status(c["id"], "Rejected", remark)
                        st.rerun()
                else:
                    options = ["In review", "Assigned", "Resolved", "Rejected"]
                    current = options.index(c["status"]) if c["status"] in options else 0
                    new_status = st.selectbox(
                        "Update status", options, index=current, key=f"status_{c['id']}"
                    )
                    if st.button("Save update", key=f"save_{c['id']}"):
                        update_status(c["id"], new_status, remark)
                        st.rerun()

                st.download_button(
                    "Download draft complaint letter",
                    draft_letter(c),
                    file_name=f"{c['id']}_draft_letter.txt",
                    key=f"dl_{c['id']}",
                )

        if complaints:
            rows = [
                {
                    "id": c["id"],
                    "created": c["created"],
                    "area": c["location"],
                    "status": c["status"],
                    "priority": c["priority"],
                    "waste_types": ", ".join((c.get("ai") or {}).get("waste_types", [])),
                    "hazard_level": (c.get("ai") or {}).get("hazard_level", ""),
                    "note": c["note"],
                }
                for c in complaints
            ]
            st.download_button(
                "Download all complaints (CSV)",
                pd.DataFrame(rows).to_csv(index=False),
                file_name="complaints.csv",
                mime="text/csv",
            )

    with tab_overview:
        m1, m2, m3, m4 = st.columns(4)
        m1.metric("Locations monitored", len(locs))
        m2.metric("Readings logged", sum(loc["readings"] for loc in locs))
        m3.metric("Action required", sum(1 for loc in locs if loc["label"] == "Action required"))
        m4.metric("Resolved", sum(1 for loc in locs if loc["label"] == "Resolved"))

        left, right = st.columns([3, 2])
        with left:
            st.subheader("Delhi spot map")
            colors = {loc["name"]: loc["color"] for loc in locs}
            st.iframe(
                build_map(style=MAP_STYLE, status_colors=colors).get_root().render(),
                height=520,
            )
            st.caption("🔴 Action required   🟡 Under watch   🟢 Resolved")

        with right:
            st.subheader("Status breakdown")
            counts = pd.DataFrame(
                {
                    "status": STATUS_LABELS,
                    "locations": [
                        sum(1 for loc in locs if loc["label"] == s) for s in STATUS_LABELS
                    ],
                }
            )
            donut = (
                alt.Chart(counts)
                .mark_arc(innerRadius=60)
                .encode(
                    theta="locations:Q",
                    color=alt.Color(
                        "status:N",
                        scale=alt.Scale(domain=STATUS_LABELS, range=[RED, YELLOW, GREEN]),
                        legend=alt.Legend(title=None),
                    ),
                )
                .properties(height=260)
            )
            st.altair_chart(donut)

            st.subheader("Recent flags")
            if flags:
                for f in reversed(flags[-4:]):
                    st.markdown(f"**{f['location']}** ({f['date']})  \n{f['reason']}")
            else:
                st.write("No locations flagged yet.")

    with tab_hot:
        st.subheader("Top hotspots")
        ranked = sorted(locs, key=lambda loc: loc["latest_coverage"], reverse=True)[:5]
        table = pd.DataFrame(
            [
                {
                    "Location": loc["name"],
                    "Score (0-100)": round(loc["latest_coverage"] * 100),
                    "Trend": loc["status"].replace("_", " "),
                    "Change (points)": round(loc["change"] * 100),
                    "Status": loc["label"],
                }
                for loc in ranked
            ]
        )
        st.dataframe(table, hide_index=True)

        st.subheader("Garbage score over time")
        st.line_chart(history_frame() * 100)
        st.caption("Readings are simulated demo data, plus any added when complaints are accepted.")

        complaints = all_complaints()
        if complaints:
            c1, c2 = st.columns(2)
            with c1:
                st.subheader("Complaints by status")
                st.bar_chart(pd.Series([c["status"] for c in complaints]).value_counts())
            with c2:
                st.subheader("Waste types seen by the AI")
                types = [
                    t
                    for c in complaints
                    if c.get("ai") and "error" not in c["ai"]
                    for t in c["ai"]["waste_types"]
                ]
                if types:
                    st.bar_chart(pd.Series(types).value_counts())
                else:
                    st.write("No AI analyses yet.")


# ---------------- Sidebar and routing ----------------
role = st.session_state["role"]

if role is not None:
    with st.sidebar:
        st.header("GarbiWatch Delhi")
        if role == "admin":
            st.success("Logged in as MCD officer")
            if st.button("Log out"):
                st.session_state["role"] = None
                st.rerun()
            st.divider()
            st.subheader("Demo controls")
            if st.button("Reset demo data"):
                reset_demo()
                st.session_state.pop("submitted_id", None)
                st.rerun()
        else:
            st.write("You are using the citizen site.")
            if st.button("Back to start"):
                st.session_state["role"] = None
                st.rerun()

if role == "admin":
    admin_view()
elif role == "citizen":
    public_view()
else:
    landing_view()