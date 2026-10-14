import hmac
import os
import shutil
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

from agent import run_agent
from complaints import (
    STATUSES,
    all_complaints,
    create_complaint,
    get_complaint,
    reset_complaints,
    set_agent_result,
    sort_for_inbox,
    update_status,
)
from dashboard import GREEN, RED, YELLOW, history_frame, load_flags, location_statuses
from detect import analyze
from heatmap import build_map
from tools import compute_severity, record_reading

MAP_STYLE = "street"  # change to "dark" to try the dark base map
STATUS_LABELS = ["Action required", "Under watch", "Resolved"]
PRIORITY_ICON = {"high": "🔴", "medium": "🟠", "low": "🟡", "unverified": "⚪"}

st.set_page_config(page_title="GarbiWatch Delhi", page_icon="🗑️", layout="wide")

if "is_admin" not in st.session_state:
    st.session_state["is_admin"] = False
if "upload_nonce" not in st.session_state:
    st.session_state["upload_nonce"] = 0


@st.cache_data(show_spinner="Looking for garbage in your photo...")
def analyze_photo(photo_bytes):
    with tempfile.NamedTemporaryFile(delete=False, suffix=".jpg") as tmp:
        tmp.write(photo_bytes)
        path = tmp.name
    try:
        return analyze(path)
    finally:
        os.remove(path)


def accept_complaint(c, remark):
    # The admin verifies the report: save the reading, then let the agent investigate
    record_reading(c["location"], c["detection"]["count"], c["detection"]["coverage"])
    update_status(c["id"], "In review", remark)
    detection = {"count": c["detection"]["count"], "coverage": c["detection"]["coverage"]}
    try:
        answer, trace = run_agent(c["location"], detection)
        flagged = any(s["tool"] == "flag_for_reinspection" for s in trace)
        set_agent_result(c["id"], answer, flagged)
    except Exception:
        set_agent_result(c["id"], "The AI agent was unavailable. Please review this one manually.", False)


# ---------------- Sidebar: who are you? ----------------
with st.sidebar:
    st.header("GarbiWatch Delhi")
    if st.session_state["is_admin"]:
        st.success("Logged in as MCD admin")
        if st.button("Log out"):
            st.session_state["is_admin"] = False
            st.rerun()
        st.divider()
        st.subheader("Demo controls")
        if st.button("Reset demo data"):
            shutil.copy("locations_original.json", "locations.json")
            if os.path.exists("flags.json"):
                os.remove("flags.json")
            reset_complaints()
            st.session_state.pop("submitted_id", None)
            st.rerun()
    else:
        st.write("You are viewing the public site.")
        with st.expander("MCD admin login"):
            password = st.text_input("Admin password", type="password")
            if st.button("Log in"):
                expected = os.getenv("ADMIN_PASSWORD")
                if not expected:
                    st.error("No admin password is set on the server.")
                elif hmac.compare_digest(password.encode(), expected.encode()):
                    st.session_state["is_admin"] = True
                    st.rerun()
                else:
                    st.error("Wrong password.")

locs = location_statuses()
flags = load_flags()
names = [loc["name"] for loc in locs]


# ---------------- Public site ----------------
def public_view():
    st.title("GarbiWatch Delhi")
    st.caption("Report garbage in your area. An AI checks your photo and the municipal team follows up.")

    tab_report, tab_track, tab_map = st.tabs(["Report garbage", "Track my complaint", "City map"])

    with tab_report:
        st.subheader("Report garbage near you")
        st.caption(
            "Prototype: complaints go to this app's admin page, not to the real MCD. "
            "Please avoid photographing people's faces or number plates."
        )

        if "submitted_id" in st.session_state:
            st.success(
                f"Complaint submitted. Your complaint ID is **{st.session_state['submitted_id']}**. "
                "Keep it to track progress in the next tab."
            )

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

            if st.button("Submit complaint"):
                severity = compute_severity(location, extra_coverage=numbers["coverage"])
                complaint = create_complaint(location, note, photo_bytes, annotated, numbers, severity)
                st.session_state["submitted_id"] = complaint["id"]
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
                if os.path.exists(c["photo"]):
                    st.image(c["photo"], width=300)
                for event in c["timeline"]:
                    st.markdown(f"- {event['time']}: {event['text']}")

    with tab_map:
        st.subheader("City map")
        colors = {loc["name"]: loc["color"] for loc in locs}
        st.iframe(build_map(style=MAP_STYLE, status_colors=colors).get_root().render(), height=520)
        st.caption("🔴 Action required   🟡 Under watch   🟢 Resolved")


# ---------------- Admin site ----------------
def admin_view():
    st.title("GarbiWatch Delhi: MCD admin")
    st.caption("Review citizen complaints, check the AI's findings, and act on them.")

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
            st.info("No complaints yet. Switch to the public site (log out) and submit one.")
        elif not shown:
            st.write("Nothing matches this filter.")

        for c in shown:
            icon = PRIORITY_ICON.get(c["priority"], "⚪")
            label = f"{icon} {c['id']} · {c['location']} · {c['priority']} priority · {c['status']}"
            with st.expander(label):
                left, right = st.columns(2)
                with left:
                    if os.path.exists(c["photo_boxes"]):
                        st.image(c["photo_boxes"], caption="AI detection")
                with right:
                    d = c["detection"]
                    sev = c["severity"]
                    st.markdown(f"**Submitted:** {c['created']}")
                    st.markdown(f"**Area:** {c['location']}")
                    st.markdown(f"**Citizen's note:** {c['note'] or 'none'}")
                    st.markdown(
                        f"**AI detection:** {d['count']} region(s), top confidence "
                        f"{d['max_confidence']}, covering {round(d['coverage'] * 100)}% of the photo"
                    )
                    st.markdown(
                        f"**Trend if accepted:** {sev['status'].replace('_', ' ')} "
                        f"({sev['priority']} priority, {sev['change_since_first_reading']:+.2f} "
                        "since the first reading)"
                    )
                    if c["agent_summary"]:
                        st.markdown("**AI agent's review**")
                        st.write(c["agent_summary"])
                        if c["agent_flagged"]:
                            st.error("Flagged for reinspection")

                st.markdown("**Timeline**")
                for event in c["timeline"]:
                    st.markdown(f"- {event['time']}: {event['text']}")

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


if st.session_state["is_admin"]:
    admin_view()
else:
    public_view()