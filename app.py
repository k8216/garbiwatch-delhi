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

from agent import run_agent
from dashboard import GREEN, RED, YELLOW, history_frame, load_flags, location_statuses
from detect import analyze
from heatmap import build_map
from tools import record_reading

MAP_STYLE = "street"  # change to "dark" to try the dark base map

st.set_page_config(page_title="GarbiWatch Delhi", page_icon="🗑️", layout="wide")

st.title("GarbiWatch Delhi")
st.caption("An AI agent that watches street garbage. Demo data: 5 simulated Delhi locations.")

with st.sidebar:
    st.header("Demo controls")
    if st.button("Reset demo data"):
        shutil.copy("locations_original.json", "locations.json")
        if os.path.exists("flags.json"):
            os.remove("flags.json")
        st.session_state.pop("last_run", None)
        st.rerun()

locs = location_statuses()
flags = load_flags()
names = [loc["name"] for loc in locs]
STATUS_LABELS = ["Action required", "Under watch", "Resolved"]

tab_overview, tab_agent, tab_hot, tab_admin = st.tabs(
    ["Overview", "AI Agent & Reasoning", "Hotspots & Analytics", "Admin & Dispatch"]
)

# ---------------- Overview ----------------
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

# ---------------- AI Agent & Reasoning ----------------
with tab_agent:
    left, right = st.columns(2)

    with left:
        st.subheader("Upload and analyze")
        location = st.selectbox("Where was this photo taken?", names)
        uploaded = st.file_uploader("Street photo", type=["jpg", "jpeg", "png"])

        if uploaded is not None:
            with tempfile.NamedTemporaryFile(delete=False, suffix=".jpg") as tmp:
                tmp.write(uploaded.getbuffer())
                path = tmp.name

            numbers, annotated = analyze(path)
            st.image(annotated, caption="Detection result", channels="RGB")

            c1, c2, c3 = st.columns(3)
            c1.metric("Garbage regions", numbers["count"])
            c2.metric("Top confidence", numbers["max_confidence"])
            c3.metric("Photo coverage", numbers["coverage"])

            if st.button("Save reading and run the agent"):
                record_reading(location, numbers["count"], numbers["coverage"])
                detection = {"count": numbers["count"], "coverage": numbers["coverage"]}
                with st.spinner("The agent is working..."):
                    answer, trace = run_agent(location, detection)
                st.session_state["last_run"] = {
                    "location": location,
                    "answer": answer,
                    "trace": trace,
                }
                st.rerun()

    with right:
        st.subheader("Agent reasoning")
        run = st.session_state.get("last_run")

        if run is None:
            st.info("Upload a photo and click the button to see the agent's decision.")
        else:
            st.caption(f"Latest run: {run['location']}")

            severity = next(
                (s["result"] for s in run["trace"] if s["tool"] == "compute_severity"),
                None,
            )
            if severity and "status" in severity:
                st.markdown("**Pattern identified**")
                st.markdown(
                    f"Trend: **{severity['status'].replace('_', ' ')}**  \n"
                    f"Priority: **{severity['priority']}**  \n"
                    f"Change since first reading: **{severity['change_since_first_reading']:+.2f}**"
                )

            did_flag = any(s["tool"] == "flag_for_reinspection" for s in run["trace"])
            if did_flag:
                st.error("Action taken: flagged for reinspection")
            else:
                st.success("Action taken: none needed, reading logged")

            st.markdown("**Agent's explanation**")
            st.write(run["answer"])

            with st.expander("Logic process (tool calls)"):
                for step in run["trace"]:
                    st.markdown(f"✅ **{step['tool']}** {step['args']}")
                    st.json(step["result"])

# ---------------- Hotspots & Analytics ----------------
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
    st.caption("Readings are simulated demo data, plus any you add by uploading photos.")

# ---------------- Admin & Dispatch ----------------
with tab_admin:
    st.subheader("Flagged for reinspection")
    if flags:
        st.dataframe(pd.DataFrame(flags)[["location", "date", "reason"]], hide_index=True)
    else:
        st.write("Nothing in the queue yet. Run the agent on a photo from the AI Agent tab.")