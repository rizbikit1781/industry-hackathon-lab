"""CivicSignal dashboard: replay of the Nov 25 - Dec 1, 2025 storm week + live plan.

Run:  .venv/bin/streamlit run civicsignal/ui.py
Reads data/results.json (scripts/run_sim.py) and, if the API is up, GET /plan.
"""
from __future__ import annotations

import json
import os
from pathlib import Path

import altair as alt
import pandas as pd
import pydeck as pdk
import requests
import streamlit as st

ROOT = Path(__file__).resolve().parents[1]
API = os.environ.get("CIVICSIGNAL_API", "http://localhost:8000")

# Reference palette (dataviz skill), validated: categorical slots 1-3, light + dark steps.
POLICY_LABEL = {"fifo": "FIFO (oldest first)", "optimized": "CivicSignal",
                "optimized_disruption": "CivicSignal + disruption"}
POLICY_COLOR = {"FIFO (oldest first)": "#eb6834", "CivicSignal": "#2a78d6",
                "CivicSignal + disruption": "#1baf7a"}
SEQ = ["#cde2fb", "#9ec5f4", "#6da7ec", "#3987e5", "#256abf", "#184f95", "#0d366b"]  # blue ramp
ROUTE_RGB = {"bylaw": [74, 58, 167], "roads": [82, 81, 78]}        # violet / neutral ink

st.set_page_config(page_title="CivicSignal", layout="wide")


@st.cache_data
def load_results():
    p = ROOT / "data" / "results.json"
    return json.loads(p.read_text()) if p.exists() else None


def hex_rgb(h):
    return [int(h[i:i + 2], 16) for i in (1, 3, 5)]


def seq_color(x):
    i = min(len(SEQ) - 1, max(0, int(x * len(SEQ))))
    return hex_rgb(SEQ[i])


R = load_results()
if R is None:
    st.error("data/results.json not found. Run `.venv/bin/python scripts/run_sim.py` first.")
    st.stop()

days = R["days"]
st.sidebar.title("CivicSignal")
st.sidebar.caption("Snow & ice field operations. Replay of Calgary's real storm week, "
                   "Nov 25 - Dec 1, 2025 (Open Calgary 311).")
view = st.sidebar.radio("Source", ["Storm-week replay", "Live plan (API)"])
policy_label = st.sidebar.radio("Policy", list(POLICY_LABEL.values()), index=1)
policy = {v: k for k, v in POLICY_LABEL.items()}[policy_label]
day_i = st.sidebar.slider("Day", 1, len(days), 1, format="Day %d")
day = days[day_i - 1]
st.sidebar.markdown(f"**{pd.Timestamp(day):%a %b %d, %Y}**")
cap = R["capacity"]
st.sidebar.caption(
    f"Capacity calibrated to median real daily closures: bylaw {cap['bylaw']['crews']} crews x "
    f"{cap['bylaw']['tickets_per_crew']}, roads {cap['roads']['crews']} crews x "
    f"{cap['roads']['tickets_per_crew']} tickets/day.")

# ------------------------------------------------------------------ headline tiles
M = {k: v["metrics"] for k, v in R["policies"].items()}
st.title("CivicSignal: the right crew to the riskiest ice first")
c1, c2, c3, c4 = st.columns(4)
f = M["fifo"]
c1.metric("High-risk tickets served within 48 h", f"{M[policy]['high_risk_within_48h']:.0%}",
          None if policy == "fifo" else f"{(M[policy]['high_risk_within_48h'] - f['high_risk_within_48h']) * 100:+.0f} pts vs FIFO")
c2.metric("Total km driven (7 days)", f"{M[policy]['total_km']:,.0f}",
          None if policy == "fifo" else f"{(M[policy]['total_km'] / f['total_km'] - 1):+.0%} vs FIFO",
          delta_color="inverse")
c3.metric("p90 days to service", f"{M[policy]['p90_days_to_service']:.0f}",
          None if policy == "fifo" else f"{M[policy]['p90_days_to_service'] - f['p90_days_to_service']:+.0f} vs FIFO",
          delta_color="inverse")
jm = M[policy]["jobs_moved_per_replan"]
c4.metric("Jobs moved per replan", "n/a" if jm is None else f"{jm:.0f}",
          None if jm is None else f"replan in {M[policy]['replan_s_max']:.0f} s", delta_color="off")

# ------------------------------------------------------------------ map
left, right = st.columns([3, 2])
with left:
    if view == "Live plan (API)":
        try:
            live = requests.get(f"{API}/plan", timeout=5).json()
            jobs = pd.DataFrame(live["jobs"])
            markers = jobs.assign(open=jobs["n_tickets"], served_today=jobs["crew"].notna().astype(int),
                                  name=jobs["comm_code"])
            routes = live["routes"]
            st.subheader(f"Live plan, {live['day']}: {len(routes)} crews, {live['km']} km")
            voice = jobs[jobs["job_id"].str.startswith("V")]
        except Exception as e:  # noqa: BLE001
            st.warning(f"API not reachable at {API} ({e}). Start it with "
                       "`.venv/bin/uvicorn civicsignal.api:app`.")
            st.stop()
    else:
        d = R["policies"][policy]["daily"][day_i - 1]
        markers = pd.DataFrame(d["markers"])
        routes = d["routes"]
        voice = pd.DataFrame()
        info = d["info"]
        st.subheader(f"{policy_label}, {day}: {info['served']} tickets served, "
                     f"{info['km']:.0f} km, {info['open_morning']} open at start")
    markers = markers.dropna(subset=["lat", "lon"]).copy()
    markers["color"] = markers["exposure"].rank(pct=True).map(seq_color)
    markers["radius"] = 60 + 25 * markers["open"].clip(upper=40)
    markers["label"] = markers["name"].fillna("").astype(str)
    rt = pd.DataFrame(routes)
    if not rt.empty:
        rt["color"] = rt["skill"].map(ROUTE_RGB)
    layers = [
        pdk.Layer("ScatterplotLayer", markers, get_position=["lon", "lat"], get_fill_color="color",
                  get_radius="radius", pickable=True, opacity=0.8, stroked=True,
                  get_line_color=[255, 255, 255], line_width_min_pixels=2),
        pdk.Layer("PathLayer", rt, get_path="path", get_color="color", width_min_pixels=2,
                  pickable=True) if not rt.empty else None,
    ]
    if len(voice):
        layers.append(pdk.Layer("ScatterplotLayer", voice, get_position=["lon", "lat"],
                                get_fill_color=[227, 73, 72], get_radius=180, pickable=True,
                                stroked=True, get_line_color=[255, 255, 255], line_width_min_pixels=2))
    st.pydeck_chart(pdk.Deck(
        layers=[l for l in layers if l is not None],
        initial_view_state=pdk.ViewState(latitude=51.04, longitude=-114.07, zoom=9.6),
        map_style="light",
        tooltip={"html": "<b>{label}</b><br/>open: {open} &middot; exposure: {exposure}<br/>{reason}"}))
    st.caption("Dots: open tickets per community (size = count, blue darkness = exposure "
               "percentile). Lines: crew routes (violet = bylaw, grey = roads). "
               "Red = live voice reports. Historical 311 locations are community centrepoints.")

# ------------------------------------------------------------------ charts
with right:
    rows = []
    for k, v in R["policies"].items():
        for dd in v["daily"]:
            rows.append({"Policy": POLICY_LABEL[k], "Day": dd["info"]["day"],
                         "High-risk tickets served": dd["info"]["high_risk_served"],
                         "km": dd["info"]["km"]})
    daily = pd.DataFrame(rows)
    color = alt.Color("Policy:N", scale=alt.Scale(domain=list(POLICY_COLOR),
                                                   range=list(POLICY_COLOR.values())),
                      legend=alt.Legend(orient="top", title=None))
    hover = alt.selection_point(fields=["Day"], nearest=True, on="pointerover", empty=False)
    base = alt.Chart(daily).encode(x=alt.X("Day:T", title=None, axis=alt.Axis(format="%b %d", grid=False)))
    lines = base.mark_line(strokeWidth=2).encode(
        y=alt.Y("High-risk tickets served:Q", axis=alt.Axis(gridOpacity=0.3)), color=color)
    pts = base.mark_point(size=80, filled=True).encode(
        y="High-risk tickets served:Q", color=color,
        opacity=alt.condition(hover, alt.value(1), alt.value(0)),
        tooltip=["Policy", alt.Tooltip("Day:T", format="%b %d"), "High-risk tickets served", "km"]
    ).add_params(hover)
    rule = base.mark_rule(color="#a3a29d").encode(
        opacity=alt.condition(hover, alt.value(0.6), alt.value(0))).transform_filter(hover)
    st.markdown("**High-risk tickets served per day**")
    st.altair_chart((lines + pts + rule).properties(height=220), width="stretch")

    km = daily.groupby("Policy", as_index=False)["km"].sum()
    bars = alt.Chart(km).mark_bar(cornerRadiusEnd=4, size=22).encode(
        y=alt.Y("Policy:N", sort=list(POLICY_COLOR), title=None),
        x=alt.X("km:Q", title="km driven over 7 days", axis=alt.Axis(gridOpacity=0.3)),
        color=alt.Color("Policy:N", scale=alt.Scale(domain=list(POLICY_COLOR),
                                                     range=list(POLICY_COLOR.values())), legend=None),
        tooltip=["Policy", alt.Tooltip("km:Q", format=",.0f")])
    labels = bars.mark_text(align="left", dx=4, color="#52514e").encode(text=alt.Text("km:Q", format=",.0f"))
    st.markdown("**Distance driven**")
    st.altair_chart((bars + labels).properties(height=130), width="stretch")

# ------------------------------------------------------------------ tables
st.markdown("### Metrics, all policies (same crews, same calibrated capacity)")
mt = pd.DataFrame(M).rename(columns=POLICY_LABEL)
show = ["high_risk_within_48h", "all_within_48h", "high_risk_served", "low_risk_served",
        "p90_days_to_service", "median_days_to_service", "tickets_served", "total_km",
        "km_per_ticket", "stops", "jobs_moved_per_replan"]
st.dataframe(mt.loc[show].astype(float).round(3), width="stretch")
for r in R["policies"]["optimized_disruption"]["replans"]:
    st.caption(f"Replan {r['kind']} on {r['day']}: {r['jobs_moved']} of {r['jobs_before']} planned "
               f"stops moved in {r['replan_s']} s; high-risk tickets planned "
               f"{r['high_risk_planned_before']} -> {r['high_risk_planned_after']}.")

st.markdown("### Top 10 open locations by exposure (why each ranks high)")
top = markers.sort_values("exposure", ascending=False).head(10)
cols = [c for c in ["label", "skill", "open", "exposure", "reason"] if c in top.columns]
st.dataframe(top[cols].rename(columns={"label": "community"}), width="stretch", hide_index=True)

with st.expander("Validation and honesty notes"):
    dv, pv = R.get("dedupe_validation", {}), R.get("ped_proxy_validation", {})
    if dv:
        st.write(f"Dedupe vs City 'Duplicate' labels: recall {dv['recall']:.0%}, precision "
                 f"{dv['precision']:.1%} (base rate {dv['base_rate']:.1%}). Public 311 points are "
                 f"community centrepoints ({dv['pct_community_centrepoint']:.0%}), so spatial "
                 "dedupe cannot separate true duplicates on historical data.")
    if pv:
        st.write(f"Pedestrian proxy vs {pv['n_sites']} real count sites: Spearman "
                 f"{pv['spearman']:.2f} (p={pv['p_value']:.2f}); not validated.")
    st.write("Closure date includes bylaw notice/compliance steps; risk weights are policy "
             "inputs; the model ranks exposure, it does not predict falls.")
