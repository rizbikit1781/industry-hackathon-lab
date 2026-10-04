"""Page B: Storm replay (0-45 min nowcast from MRMS radar, replayed from precomputed files)."""
from __future__ import annotations

import base64
import io
import time

import altair as alt
import numpy as np
import pandas as pd
import pydeck as pdk
import streamlit as st
from PIL import Image

import data
import ui

PLAY_DELAY_S = 0.6
KM_PER_DEG_LAT = 111.0


# ---------- grid -> bitmap ----------

def _axis(spec, n):
    try:
        a = np.asarray(spec, dtype=float).ravel()
    except Exception:
        return None
    if a.size == n:
        return a
    if a.size == 2 and n > 1:
        return np.linspace(a[0], a[1], n)
    return None


def grid_axes(rp: dict, fields: dict | None, ny: int, nx: int):
    g = rp.get("grid") or {}
    lats = _axis(g.get("lats"), ny)
    lons = _axis(g.get("lons"), nx)
    if (lats is None or lons is None) and fields:
        lats = lats if lats is not None else _axis(fields.get("lats"), ny)
        lons = lons if lons is not None else _axis(fields.get("lons"), nx)
    return lats, lons


def _ramp(values, stops):
    """values (float array) -> RGBA uint8 via piecewise-linear colour stops [(v, r, g, b, a), ...]."""
    s = np.asarray(stops, dtype=float)
    out = np.zeros(values.shape + (4,), dtype=np.uint8)
    for c in range(4):
        out[..., c] = np.interp(values, s[:, 0], s[:, c + 1], left=0 if c == 3 else s[0, c + 1]).astype(np.uint8)
    out[values < s[0, 0], 3] = 0
    return out


MESH_STOPS = [(5, 255, 235, 120, 120), (20, 255, 170, 0, 190), (30, 240, 80, 0, 215), (50, 180, 0, 40, 235),
              (75, 120, 0, 120, 245)]
P30_STOPS = [(10, 130, 160, 255, 70), (30, 70, 100, 230, 140), (50, 40, 40, 200, 190), (80, 90, 0, 170, 230)]


def bitmap_layer(arr2d, lats, lons, stops, layer_id):
    if arr2d is None or lats is None or lons is None:
        return None
    a = np.asarray(arr2d, dtype=float)
    if lats[0] < lats[-1]:          # image row 0 must be north
        a = a[::-1]
        lats = lats[::-1]
    if lons[0] > lons[-1]:
        a = a[:, ::-1]
        lons = lons[::-1]
    rgba = _ramp(a, stops)
    if rgba[..., 3].max() == 0:
        return None
    buf = io.BytesIO()
    Image.fromarray(rgba, "RGBA").save(buf, format="PNG")
    url = "data:image/png;base64," + base64.b64encode(buf.getvalue()).decode()
    dy = abs(lats[0] - lats[1]) / 2 if len(lats) > 1 else 0.005
    dx = abs(lons[1] - lons[0]) / 2 if len(lons) > 1 else 0.005
    bounds = [float(lons[0] - dx), float(lats[-1] - dy), float(lons[-1] + dx), float(lats[0] + dy)]
    # String() keeps the data URL literal; a bare string is serialized as a deck.gl expression ("@@=...").
    return pdk.Layer("BitmapLayer", id=layer_id, image=pdk.types.String(url), bounds=bounds, opacity=0.9)


# ---------- timeline helpers ----------

def _mm(x) -> str:
    try:
        return f"{float(x):.0f} mm"
    except (TypeError, ValueError):
        return "-"


def asset_state_at(asset: dict, issue: str) -> dict:
    for row in asset.get("timeline") or []:
        if row.get("issue_time") == issue:
            return row
    return {}


def _plain_expr() -> str:
    """Vega label expression mapping raw state names to plain words (data keeps the raw names)."""
    expr = "datum.label"
    for k, v in ui.PLAIN.items():
        expr = f"datum.label == '{k}' ? '{v}' : ({expr})"
    return expr


def timeline_chart(asset: dict, issues: list[str]):
    tl = pd.DataFrame(asset.get("timeline") or [])
    if tl.empty or "issue_time" not in tl:
        st.info("No timeline for this site.")
        return
    t = tl["issue_time"].map(data.to_mdt)
    tl = tl.assign(_t=t).dropna(subset=["_t"]).sort_values("_t")
    if tl.empty:
        st.info("No timeline for this site.")
        return
    fake = lambda s: s.dt.strftime("%Y-%m-%dT%H:%M:%SZ")     # MDT wall clock shown via a UTC scale
    step = (tl["_t"].diff().median() if len(tl) > 1 else pd.Timedelta(minutes=10)) or pd.Timedelta(minutes=10)
    tl["t"] = fake(tl["_t"])
    tl["t2"] = fake(tl["_t"].shift(-1).fillna(tl["_t"].iloc[-1] + step))
    tl["state"] = tl.get("state", pd.Series("NONE", index=tl.index)).fillna("NONE").astype(str).str.upper()
    for c in ("p20", "p30", "p50"):
        tl[c] = pd.to_numeric(tl[c], errors="coerce") if c in tl else np.nan
    states = [s for s in ui.STATE_ORDER if s in set(tl["state"])] + sorted(set(tl["state"]) - set(ui.STATE_ORDER))
    xs = alt.X("t:T", scale=alt.Scale(type="utc"), axis=alt.Axis(format="%H:%M", title="Issue time (MDT)"))
    bands = alt.Chart(tl).mark_rect(opacity=0.35).encode(
        x=xs, x2="t2:T",
        color=alt.Color("state:N", scale=alt.Scale(domain=states, range=[ui.STATE_HEX.get(s, "#999999") for s in states]),
                        legend=alt.Legend(title="State", orient="top", labelExpr=_plain_expr())),
        tooltip=["state"])
    line = alt.Chart(tl).mark_line(point=True, strokeWidth=3, color="#111111").encode(
        x=xs, y=alt.Y("p30:Q", scale=alt.Scale(domain=[0, 1]), axis=alt.Axis(format="%", title="P(hail >= 30 mm)")),
        tooltip=[alt.Tooltip("p30:Q", format=".0%"), alt.Tooltip("p50:Q", format=".0%")])
    layers = [bands, line]
    first = data.to_mdt((asset.get("observed") or {}).get("first_ge30_time"))
    if first is not None:
        r = pd.DataFrame({"t": [first.strftime("%Y-%m-%dT%H:%M:%SZ")], "label": ["observed hail >= 30 mm"]})
        layers.append(alt.Chart(r).mark_rule(color="#c81e2d", strokeWidth=3, strokeDash=[6, 4]).encode(
            x=alt.X("t:T", scale=alt.Scale(type="utc")), tooltip=["label"]))
        layers.append(alt.Chart(r).mark_text(align="left", dx=5, dy=-120, color="#c81e2d", fontSize=14,
                                             fontWeight="bold").encode(x=alt.X("t:T", scale=alt.Scale(type="utc")),
                                                                       text="label"))
    st.altair_chart(alt.layer(*layers).properties(height=280), width="stretch")


def eval_table(ev: dict):
    if not isinstance(ev, dict) or not ev:
        st.info("Evaluation not yet computed for this event.")
        return
    names = {"nowcast": "HailTech nowcast", "persistence": "Persistence (storm stays put)",
             "mesh_only": "MESH only (alert when hail is overhead)"}
    rows = []
    for k in ["nowcast", "persistence", "mesh_only"] + [k for k in ev if k not in names]:
        e = ev.get(k)
        if not isinstance(e, dict):
            continue
        rows.append({"Method": names.get(k, k),
                     "Hits caught": f"{e.get('hits_caught', '-')} / {e.get('hits_total', '-')}",
                     "Median lead (min)": e.get("median_lead_min"),
                     "False alarms": e.get("false_alarms"),
                     "False triggers": e.get("false_triggers")})
    t = pd.DataFrame(rows).dropna(axis=1, how="all")
    st.dataframe(t, hide_index=True, width="stretch",
                 column_config={"Median lead (min)": st.column_config.NumberColumn(format="%.0f")})
    st.caption("A hit is caught only if the site was already at 'Get ready' (ARM) or 'Act now' (TRIGGER) before hail >= 30 mm arrived; "
               "lead = minutes of warning.")
    grid = []
    for k, e in ev.items():
        for gk, g in (e or {}).items() if isinstance(e, dict) else []:
            if gk.startswith("grid") and isinstance(g, dict):
                grid.append({"Method": names.get(k, k), "Score": gk, "Lead (min)": g.get("lead_min"),
                             "P cut (%)": g.get("p_cut_pct"), "POD": g.get("pod"), "CSI": g.get("csi"),
                             "FSS (9 px)": g.get("fss_9px_mean"), "Issues scored": g.get("n_issues_scored")})
    if grid:
        with st.expander("Grid-point skill (pixel verification, harsher than per-site)"):
            st.dataframe(pd.DataFrame(grid), hide_index=True, width="stretch")


# ---------- task feasibility, ECCC, NHP ----------

TASK_RGB = {"FEASIBLE": ui.GREEN, "TIGHT": ui.AMBER, "MISSED": ui.GREY, "BLOCKED_UNSAFE": ui.RED,
            "NOT_NEEDED": ui.LIGHT}
TASK_LABEL = {"FEASIBLE": "Feasible", "TIGHT": "Tight (<10 min slack)", "MISSED": "Missed",
              "BLOCKED_UNSAFE": ui.plain("BLOCKED_UNSAFE"), "NOT_NEEDED": "Not needed"}
NHP_RGB = {"Severe": [150, 0, 60, 150], "Moderate": [220, 60, 30, 130], "Minor": [245, 150, 30, 110],
           "Threshold": [250, 215, 90, 90]}
NHP_GEOJSON = data.DATA / "raw" / "nhp" / "NHP_August2024_DamageContours.geojson"


@st.cache_data(show_spinner=False)
def _read_json_file(path: str, _mt: float):
    import json
    with open(path) as fh:
        return json.load(fh)


def _json_file(path) -> dict | None:
    try:
        return _read_json_file(str(path), path.stat().st_mtime) if path.is_file() else None
    except Exception:
        return None


def eccc_warnings(ev_date: str) -> dict | None:
    d = _json_file(data.DATA / "official" / f"eccc_warnings_{ev_date}.json")
    return d if isinstance(d, dict) else None


def eccc_status_at(ec: dict | None, issue: str):
    """Latest ECCC timeline entry at or before the issue time, or None."""
    t = data.to_mdt(issue)
    if not ec or t is None:
        return None
    best, best_t = None, None
    for e in ec.get("timeline") or []:
        if not isinstance(e, dict):
            continue
        et = data.to_mdt(e.get("time_mdt"))
        if et is not None and et <= t and (best_t is None or et >= best_t):
            best, best_t = e, et
    return best


def eccc_banner(ec: dict | None, issue: str):
    if ec is None:
        st.caption("Official ECCC status: archive not available for this event.")
        return
    e = eccc_status_at(ec, issue)
    when = data.hhmm(issue)
    if e is None:
        st.info(f"**Official ECCC status at {when} MDT:** no warning issued yet for this area. "
                "Official warnings always take precedence over HailTech.")
        return
    text = (f"**Official ECCC status at {when} MDT:** {e.get('product', 'warning')} "
            f"({data.hhmm(e.get('time_mdt'))} MDT, {e.get('severity', '-')}) for {e.get('area', '-')}. "
            f"Hail: {e.get('hail_wording', '-')}. "
            + ("**Covers Calgary.** " if e.get("covers_calgary") else "Not yet covering Calgary. ")
            + "Official warnings always take precedence over HailTech.")
    (st.error if e.get("covers_calgary") else st.warning)(text)


def _first_calgary_warning(ec: dict | None):
    for e in sorted([e for e in (ec or {}).get("timeline") or [] if isinstance(e, dict)],
                    key=lambda e: str(e.get("time_mdt"))):
        if e.get("covers_calgary"):
            return e
    return None


def _covered(address: str, area: str) -> bool:
    addr = str(address or "").lower()
    towns = [w.strip().lower() for w in str(area or "").replace("City of", "").split(",") if w.strip()]
    return any(t and t in addr for t in towns)


def eccc_vs_hailday(ec: dict | None, rp: dict, nhp: dict | None):
    st.subheader("ECCC warning (whole city) vs HailTech (per site)")
    if ec is None:
        st.info("ECCC warning archive (data/official/eccc_warnings_<event>.json) not available for this event.")
        return
    first = _first_calgary_warning(ec)
    cmp_ = ec.get("comparison") or {}
    per = ((rp.get("evaluation") or {}).get("nowcast") or {}).get("per_asset") or {}
    addr = {}
    adf = data.assets_csv()
    if adf is not None and {"asset_id", "address"} <= set(adf.columns):
        addr = dict(zip(adf["asset_id"], adf["address"]))
    grades = {r.get("asset_id"): r.get("nhp_grade") for r in (nhp or {}).get("assets") or [] if isinstance(r, dict)}
    truth = float((rp.get("thresholds") or {}).get("truth_mm", 30))
    rows = []
    for a in rp.get("assets") or []:
        if not isinstance(a, dict):
            continue
        aid = a.get("asset_id")
        mx = (a.get("observed") or {}).get("max_mesh_mm")
        row = {"Site": a.get("name", aid),
               "ECCC covered at first Calgary warning": ("yes" if _covered(addr.get(aid), first.get("area"))
                                                          else "no") if first else "-",
               f"HailTech first '{ui.plain('ARM')}' (MDT)": data.hhmm((per.get(aid) or {}).get("first_arm")),
               f"Observed hit (MESH >= {truth:.0f} mm)": "yes" if mx is not None and mx >= truth else "no"}
        if grades:
            row["NHP damage grade"] = grades.get(aid) or "-"
        rows.append(row)
    if rows:
        st.dataframe(pd.DataFrame(rows), hide_index=True, width="stretch", height=300)
    t_ec = first.get("time_mdt") if first else None
    hit_arms = sorted(str((per.get(a.get("asset_id")) or {}).get("first_arm")) for a in rp.get("assets") or []
                      if isinstance(a, dict) and (a.get("observed") or {}).get("first_ge30_time")
                      and (per.get(a.get("asset_id")) or {}).get("first_arm"))
    first_hit_arm = data.hhmm(hit_arms[0]) if hit_arms else cmp_.get("hailday_first_arm_mdt", "-")
    st.caption(f"ECCC first warned the City of Calgary at {cmp_.get('first_calgary_warning_mdt') or data.hhmm(t_ec)} "
               f"MDT; HailTech's first ARM at a site that was later hit was {first_hit_arm} MDT. "
               "ECCC warned the whole city 9 min before HailTech's first ARM; HailTech's value is which sites act "
               "and which stand down, not earlier warning. (Any earlier HailTech ARM in the table was at a site "
               "that did not reach MESH >= 30 mm, i.e. a false alarm, not an earlier catch.)")
    st.caption(f"Source: {ec.get('source', 'ECCC')}. Licence: {ec.get('licence', '-')}.")


def feasibility_table(rp: dict, issue: str):
    rows = []
    for a in rp.get("assets") or []:
        if not isinstance(a, dict):
            continue
        tk = a.get("task") or {}
        now = asset_state_at(a, issue)
        if not tk and "task_window_status" not in now:
            continue
        stt = now.get("task_window_status")
        rows.append({"Site": a.get("name", a.get("asset_id")),
                     "Task (min)": tk.get("task_duration_min"),
                     f"First '{ui.plain('ARM')}'": data.hhmm(tk.get("first_arm")),
                     "Lead at first ARM (min)": tk.get("observed_lead_min"),
                     "Slack at first ARM (min)": tk.get("slack_at_first_arm_min"),
                     f"At first '{ui.plain('ARM')}'": TASK_LABEL.get(tk.get("status_at_first_arm"), "-"),
                     "Ever feasible": "yes" if tk.get("feasible") else ("no" if tk.get("first_arm") else "-"),
                     "Now": TASK_LABEL.get(stt, "-"),
                     "Latest start now": data.hhmm(now.get("latest_feasible_start")),
                     "_hit": (a.get("observed") or {}).get("first_ge30_time") is not None,
                     "_warned": bool(tk.get("first_arm"))})
    if not rows:
        st.info("Task feasibility not computed for this replay (re-run scripts/replay_nowcast.py).")
        return
    df = pd.DataFrame(rows).sort_values(["_hit", "_warned"], ascending=False).drop(columns=["_hit", "_warned"])
    st.dataframe(df, hide_index=True, width="stretch", height=320,
                 column_config={c: st.column_config.NumberColumn(format="%.0f") for c in
                                ("Task (min)", "Lead at first ARM (min)", "Slack at first ARM (min)")})
    st.caption("Latest feasible start = earliest forecast arrival - task duration - 5 min margin. Task durations "
               "are category ASSUMPTIONS (dealer 45, rental/fleet 30, transit 25, airport/RV/nursery 20, solar 10 "
               "min). BLOCKED_UNSAFE: arrival <= 15 min away or hail already within 10 km (lightning proxy, ECCC "
               "guidance) - shelter, do not go outside. A 45-min dealer task never fits inside a 45-min nowcast: "
               "it needs the day-ahead PREPARE call.")


def nhp_section(ev_date: str, rp: dict):
    st.subheader("Independent check: NHP damage contours")
    v = data.load_json(f"nowcast/nhp_validation_{ev_date}.json")
    if not isinstance(v, dict):
        ui.not_computed("NHP damage-contour check", f"nowcast/nhp_validation_{ev_date}.json",
                        "Run `python scripts/validate_nhp.py` (Northern Hail Project survey, 5 Aug 2024 only).")
        return
    s = v.get("summary") or {}
    gj = _json_file(NHP_GEOJSON)
    layers = []
    if isinstance(gj, dict) and gj.get("features"):
        feats = []
        for f in gj["features"]:
            g = (f.get("properties") or {}).get("DamageType")
            feats.append({"type": "Feature", "geometry": f.get("geometry"),
                          "properties": {"grade": g, "fill": NHP_RGB.get(g, [150, 150, 150, 80])}})
        order = {"Threshold": 0, "Minor": 1, "Moderate": 2, "Severe": 3}
        feats.sort(key=lambda f: order.get(f["properties"]["grade"], -1))
        layers.append(pdk.Layer("GeoJsonLayer", {"type": "FeatureCollection", "features": feats},
                                get_fill_color="properties.fill", get_line_color=[80, 0, 0, 160],
                                line_width_min_pixels=1, stroked=True, filled=True, pickable=True))
    rows = [r for r in v.get("assets") or [] if isinstance(r, dict)]
    pos = {a.get("asset_id"): (a.get("lat"), a.get("lon")) for a in rp.get("assets") or [] if isinstance(a, dict)}
    pts = []
    for r in rows:
        la, lo = pos.get(r.get("asset_id"), (None, None))
        if la is None:
            continue
        col = ui.RED if r.get("mesh_hit") else (ui.AMBER if r.get("warned") else ui.BLUE)
        pts.append({"lat": la, "lon": lo, "name": r.get("name"), "grade": r.get("nhp_grade"),
                    "color": col, "dist": r.get("dist_km")})
    if pts:
        layers.append(pdk.Layer("ScatterplotLayer", pd.DataFrame(pts), get_position="[lon, lat]",
                                get_fill_color="color", get_radius=400, radius_min_pixels=7, stroked=True,
                                get_line_color=[255, 255, 255], line_width_min_pixels=2, pickable=True))
    c1, c2 = st.columns([1.6, 1])
    with c1:
        if layers:
            ui.deck(layers, tooltip={"html": "<b>{name}</b> {grade}<br/>nearest contour {dist} km",
                                     "style": {"fontSize": "14px"}}, height=420)
        if gj is None:
            st.caption("Contour polygons not cached locally (data/raw/nhp/); table only.")
        ui.legend([("Severe", NHP_RGB["Severe"][:3]), ("Moderate", NHP_RGB["Moderate"][:3]),
                   ("Minor", NHP_RGB["Minor"][:3]), ("Threshold", NHP_RGB["Threshold"][:3]),
                   ("Site: MESH hit", ui.RED), ("Site: warned, no MESH hit", ui.AMBER), ("Site: not warned", ui.BLUE)])
    with c2:
        if rows:
            t = pd.DataFrame([{"Site": r.get("name"), "NHP grade": r.get("nhp_grade"), "Dist (km)": r.get("dist_km"),
                               "Warned": "yes" if r.get("warned") else "no",
                               "MESH hit": "yes" if r.get("mesh_hit") else "no"} for r in rows])
            st.dataframe(t, hide_index=True, width="stretch", height=380)
    if s.get("verdict"):
        st.markdown(f"**Finding:** {s['verdict']}")
    for note in v.get("notes") or []:
        st.caption(note)
    src = v.get("source") or {}
    st.caption(f"Source: {src.get('citation', src.get('name', 'Northern Hail Project'))} "
               f"Licence {v.get('licence', 'CC BY-NC 4.0')}; validation only.")


# ---------- page ----------

def _advance(key_idx: str, n: int):
    """Called at the top of a run (before the slider exists) when the player is running."""
    if st.session_state.pop("rp_advance", False):
        nxt = int(st.session_state.get(key_idx, 0)) + 1
        if nxt >= n:
            st.session_state["rp_playing"] = False
            nxt = n - 1
        st.session_state[key_idx] = nxt


def render():
    st.title("Storm replay")
    st.caption("Nowcast layer, 0 to 45 minutes ahead from NOAA MRMS radar. Replayed from precomputed files: "
               "each frame is what HailTech would have issued at that time.")
    dates = data.replay_dates()
    if not dates:
        ui.not_computed("Storm replay", "data/processed/nowcast/replay_<YYYY-MM-DD>.json (+ _fields.npz)")
        return
    ev_date = st.selectbox("Event", dates, index=dates.index("2024-08-05") if "2024-08-05" in dates else 0,
                           key="rp_event")
    rp, fields = data.replay(ev_date)
    if rp is None:
        ui.not_computed(f"Replay {ev_date}", f"nowcast/replay_{ev_date}.json (missing or unreadable)")
        return
    ui.fixture_banner(f"nowcast/replay_{ev_date}.json")
    if rp.get("event"):
        st.markdown(f"**{rp['event']}**")

    issues = [str(x) for x in rp.get("issue_times") or []]
    n = len(issues)
    key_idx = f"rp_idx_{ev_date}"
    st.session_state.setdefault(key_idx, 0)
    st.session_state.setdefault("rp_playing", False)
    _advance(key_idx, n)
    if st.session_state[key_idx] >= n:
        st.session_state[key_idx] = n - 1

    def step(delta):
        st.session_state[key_idx] = int(np.clip(st.session_state.get(key_idx, 0) + delta, 0, n - 1))
        st.session_state["rp_playing"] = False

    def toggle():
        playing = not st.session_state.get("rp_playing", False)
        if playing and st.session_state.get(key_idx, 0) >= n - 1:
            st.session_state[key_idx] = 0
        st.session_state["rp_playing"] = playing

    c1, c2, c3, c4 = st.columns([0.6, 0.8, 0.6, 5])
    c1.button("< Back", on_click=step, args=(-1,), width="stretch", key="rp_back")
    c2.button("Pause" if st.session_state["rp_playing"] else "Play", on_click=toggle, width="stretch",
              key="rp_play", type="primary")
    c3.button("Next >", on_click=step, args=(1,), width="stretch", key="rp_next")
    with c4:
        if n > 1:
            st.select_slider("Issue time (MDT)", options=list(range(n)), key=key_idx,
                             format_func=lambda i: data.hhmm(issues[i]), label_visibility="collapsed")
    i = int(st.session_state[key_idx])
    issue = issues[i]

    # official warnings take precedence: pinned above HailTech's own states
    eccc_banner(eccc_warnings(ev_date), issue)
    blocked = [a.get("name", a.get("asset_id")) for a in rp.get("assets") or [] if isinstance(a, dict)
               and asset_state_at(a, issue).get("task_window_status") == "BLOCKED_UNSAFE"]
    if blocked:
        st.error(f"**{ui.plain('BLOCKED_UNSAFE')} - do not go outside** at {len(blocked)} site(s): " + ", ".join(map(str, blocked[:8]))
                 + (" ..." if len(blocked) > 8 else "")
                 + ". Hail is within 15 min or already within 10 km (lightning risk); outdoor protective "
                   "work is not recommended.")

    leads = [int(x) for x in (rp.get("leads_min") or [0, 10, 20, 30, 45])]
    o1, o2, o3 = st.columns([2.2, 1, 1])
    lead = o1.radio("Forecast lead (min)", leads, index=leads.index(30) if 30 in leads else 0,
                    horizontal=True, key="rp_lead")
    show_obs = o2.checkbox("Observed MESH", value=True, key="rp_obs")
    show_fc = o3.checkbox("Forecast P(>=30 mm)", value=True, key="rp_fc")

    # map layers
    layers = []
    obs = fields.get("obs_mesh") if fields else None
    fc = fields.get("fcst_p30") if fields else None
    if fields is None:
        st.caption("Radar fields file not found; showing storms and sites only.")
    fi = i
    if fields is not None and "issue_times" in fields:
        ft = [str(x) for x in np.asarray(fields["issue_times"]).ravel()]
        fi = ft.index(issue) if issue in ft else (i if i < len(ft) else None)
    if obs is not None and obs.ndim == 3 and fi is not None and fi < obs.shape[0]:
        lats, lons = grid_axes(rp, fields, obs.shape[1], obs.shape[2])
        if show_obs:
            layers.append(bitmap_layer(obs[fi], lats, lons, MESH_STOPS, "obs"))
    if fc is not None and fc.ndim == 4 and fi is not None and fi < fc.shape[0] and show_fc:
        lats, lons = grid_axes(rp, fields, fc.shape[2], fc.shape[3])
        li = leads.index(lead) if lead in leads and leads.index(lead) < fc.shape[1] else 0
        layers.append(bitmap_layer(fc[fi, li], lats, lons, P30_STOPS, "fc"))
    layers = [l for l in layers if l is not None]

    storms = pd.DataFrame([s for s in rp.get("storms") or [] if isinstance(s, dict) and s.get("issue_time") == issue])
    if not storms.empty and {"lat", "lon"} <= set(storms.columns):
        for c in ("u_kmh", "v_kmh", "max_mesh_mm", "area_km2"):
            storms[c] = pd.to_numeric(storms[c], errors="coerce").fillna(0.0) if c in storms else 0.0
        h = 30 / 60   # arrow = 30 min of motion
        storms["lat2"] = storms["lat"] + storms["v_kmh"] * h / KM_PER_DEG_LAT
        storms["lon2"] = storms["lon"] + storms["u_kmh"] * h / (KM_PER_DEG_LAT * np.cos(np.radians(storms["lat"])))
        storms["spd"] = np.hypot(storms["u_kmh"], storms["v_kmh"]).round(0)
        storms["sid"] = storms.get("storm_id", pd.Series("", index=storms.index)).astype(str)
        sd = storms[["lat", "lon", "lat2", "lon2", "spd", "sid", "max_mesh_mm", "area_km2"]]
        layers += [
            pdk.Layer("LineLayer", sd, get_source_position="[lon, lat]", get_target_position="[lon2, lat2]",
                      get_color=[20, 20, 20], get_width=5, width_min_pixels=4),
            pdk.Layer("ScatterplotLayer", sd, get_position="[lon2, lat2]", get_fill_color=[20, 20, 20],
                      get_radius=500, radius_min_pixels=5),
            pdk.Layer("ScatterplotLayer", sd, get_position="[lon, lat]", get_fill_color=[255, 255, 255],
                      get_line_color=[20, 20, 20], stroked=True, line_width_min_pixels=3, get_radius=900,
                      radius_min_pixels=9, pickable=True),
        ]

    arows = []
    for a in rp.get("assets") or []:
        if not isinstance(a, dict):
            continue
        r = asset_state_at(a, issue)
        stt = str(r.get("state") or "NONE").upper()
        obsd = a.get("observed") or {}
        arows.append({"asset_id": a.get("asset_id"), "name": a.get("name", a.get("asset_id")),
                      "lat": a.get("lat"), "lon": a.get("lon"), "state": stt,
                      "color": ui.STATE_RGB.get(stt, ui.GREY), "label": ui.plain(stt), "p30": ui.pct(r.get("p30")),
                      "arr": data.hhmm(r.get("arrival_likely")),
                      "obs": _mm(obsd.get("max_mesh_mm")), "first": data.hhmm(obsd.get("first_ge30_time")),
                      "task_min": (a.get("task") or {}).get("task_duration_min"),
                      "latest": data.hhmm(r.get("latest_feasible_start")),
                      "task": TASK_LABEL.get(r.get("task_window_status"), "-")})
    adf = pd.DataFrame(arows)
    if not adf.empty:
        adf = adf.dropna(subset=["lat", "lon"])
        layers.append(pdk.Layer("ScatterplotLayer", adf, get_position="[lon, lat]", get_fill_color="color",
                                get_radius=450, radius_min_pixels=8, radius_max_pixels=22, stroked=True,
                                get_line_color=[255, 255, 255], line_width_min_pixels=2, pickable=True))
    tip = {"html": "<b>{name}</b> {sid}<br/>{label}<br/>P(>=30 mm, 45 min): {p30}<br/>Likely arrival: {arr}<br/>"
                   "Observed max hail size from radar: {obs} (first >= 30 mm at {first})<br/>Task: {task} (latest start {latest})"
                   "<br/>{spd} km/h", "style": {"fontSize": "15px"}}

    mc, sc = st.columns([2.2, 1])
    with mc:
        ui.deck(layers, tooltip=tip, height=540)
        ui.legend([(ui.plain("TRIGGER"), ui.RED), (ui.plain("ARM"), ui.AMBER),
                   (f'{ui.plain("MONITOR")} (no action)', ui.BLUE), (ui.plain("ALL_CLEAR"), ui.GREEN),
                   ("Radar data degraded", ui.LIGHT)])
        st.caption("Orange-red shading: observed hail size from radar (MESH) at this frame. Blue-purple shading: forecast P(hail >= 30 mm) "
                   f"at +{lead} min. White circles: storm cells; black arrow: next 30 min of motion.")
    with sc:
        st.markdown(f"### {data.hhmm(issue)} MDT")
        if not adf.empty:
            k = adf["state"].value_counts()
            m1, m2 = st.columns(2)
            m1.metric(ui.plain("TRIGGER"), int(k.get("TRIGGER", 0)))
            m2.metric(ui.plain("ARM"), int(k.get("ARM", 0)))
            hot = adf[adf["state"].isin(["TRIGGER", "ARM"])].sort_values("state", ascending=False)
            if not hot.empty:
                st.dataframe(hot.assign(state=hot["state"].map(ui.plain))[["name", "state", "p30", "arr", "task_min", "latest", "task"]].rename(
                    columns={"name": "Site", "state": "State", "p30": "P30", "arr": "Arrival",
                             "task_min": "Task (min)", "latest": "Latest start", "task": "Task status"}),
                    hide_index=True, width="stretch", height=260)
        if not storms.empty:
            st.caption(f"{len(storms)} storm cell(s); max MESH {storms['max_mesh_mm'].max():.0f} mm.")

    st.subheader("Site timeline")
    assets = [a for a in rp.get("assets") or [] if isinstance(a, dict)]
    if assets:
        def score(a):
            obsd = a.get("observed") or {}
            return (obsd.get("first_ge30_time") is not None,
                    max([float(x.get("p30") or 0) for x in a.get("timeline") or []] or [0]))
        default = max(range(len(assets)), key=lambda k: score(assets[k]))
        k = st.selectbox("Site", range(len(assets)), index=default, key=f"rp_asset_{ev_date}",
                         format_func=lambda k: f"{assets[k].get('name', assets[k].get('asset_id'))}")
        now = asset_state_at(assets[k], issue)
        stt = now.get("task_window_status")
        if stt:
            tk = assets[k].get("task") or {}
            st.markdown(f"Protective task at {data.hhmm(issue)} MDT: "
                        + ui.badge(TASK_LABEL.get(stt, stt), TASK_RGB.get(stt, ui.GREY))
                        + f" &nbsp; {tk.get('task_duration_min', '-'):.0f} min task, latest start "
                        f"{data.hhmm(now.get('latest_feasible_start'))} MDT. {now.get('task_message') or ''}"
                        if isinstance(tk.get("task_duration_min"), (int, float)) else
                        "Protective task: " + ui.badge(TASK_LABEL.get(stt, stt), TASK_RGB.get(stt, ui.GREY)),
                        unsafe_allow_html=True)
        timeline_chart(assets[k], issues)

    st.subheader("Can the protective task still be done in time?")
    feasibility_table(rp, issue)

    st.subheader("Did it work? Nowcast vs baselines")
    eval_table(rp.get("evaluation"))
    eccc_vs_hailday(eccc_warnings(ev_date), rp, data.load_json(f"nowcast/nhp_validation_{ev_date}.json"))
    nhp_section(ev_date, rp)
    with st.expander("Per-site lead times and notes"):
        ev = rp.get("evaluation") or {}
        nc = ev.get("nowcast") if isinstance(ev, dict) else None
        per = (nc.get("per_asset") if isinstance(nc, dict) else None) or {}
        if isinstance(per, dict) and per:
            names = {a.get("asset_id"): a.get("name") for a in assets}
            st.dataframe(pd.DataFrame([{"Site": names.get(aid, aid), f"First '{ui.plain('ARM')}'": data.hhmm(v.get("first_arm")),
                                        f"First '{ui.plain('TRIGGER')}'": data.hhmm(v.get("first_trigger")),
                                        "Lead (min)": v.get("lead_min")} for aid, v in per.items()
                                       if isinstance(v, dict)]), hide_index=True, width="stretch")
        if rp.get("thresholds"):
            st.json(rp["thresholds"])
        for note in rp.get("notes") or []:
            st.markdown(f"- {note}")

    if st.session_state.get("rp_playing"):
        if i >= n - 1:
            st.session_state["rp_playing"] = False
            st.rerun()   # redraw the button as "Play"
        else:
            time.sleep(PLAY_DELAY_S)
            st.session_state["rp_advance"] = True
            st.rerun()
