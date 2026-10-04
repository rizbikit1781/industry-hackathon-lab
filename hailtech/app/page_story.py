"""Front page: the 5 August 2024 storm, told in plain words for people with no weather or ML background.

Everything shown is read from the precomputed files (replay JSON + radar npz, ECCC archive, morning score);
only the wording lives here. Raw state names stay in the data; ui.plain() turns them into words.
"""
from __future__ import annotations

import html
import time
from dataclasses import dataclass, field

import numpy as np
import pandas as pd
import pydeck as pdk
import streamlit as st

import data
import ui
from page_replay import MESH_STOPS, asset_state_at, bitmap_layer, eccc_warnings, grid_axes

EVENT = "2024-08-05"
TITLE = "The 5 August 2024 storm"
HIT_MM_DEFAULT = 30.0
AIRPORT = (51.1215, -114.0076)        # YYC terminal, for "near the airport" wording only
NEAR_AIRPORT_KM = 12.0
INLINE_NAMES = 3                        # bigger groups get "N businesses ..." plus a small name line
EDGE_KM = 10.0                          # a false alarm within this distance of damaging hail is "near the edge"
PLAY_FAST_S, PLAY_SLOW_S = 0.3, 1.0     # quiet frames fly by; frames that add to the feed linger
VIEW = dict(latitude=51.10, longitude=-114.02, zoom=10.1, pitch=0, bearing=0)

CATEGORY = {"dealer": "Car dealer", "rental_lot": "Car rental lot", "airport_parking": "Airport parking",
            "fleet_lot": "Truck & van fleet", "rv_storage": "RV storage", "transit": "LRT train yard",
            "nursery_greenhouse": "Garden nursery", "solar": "Solar farm"}
SIZES = [(50, "hen's-egg-sized or bigger"), (45, "golf-ball-sized"), (38, "almost golf-ball-sized"),
         (28, "toonie-sized or a bit bigger"), (26, "loonie-sized"), (20, "nickel-sized")]
PAST_STOPS = [(10, 150, 120, 95, 45), (30, 130, 95, 70, 85), (60, 110, 70, 50, 110)]


# ---------- small helpers ----------

def clock(t) -> str:
    t = data.to_mdt(t)
    return "-" if t is None else t.strftime("%I:%M %p").lstrip("0")


def short(name) -> str:
    return str(name or "?").split(" (")[0].strip()


def size_words(mm) -> str:
    try:
        mm = float(mm)
    except (TypeError, ValueError):
        return ""
    for lo, words in SIZES:
        if mm >= lo:
            return words
    return "smaller than a nickel"


def km(lat1, lon1, lat2, lon2) -> float:
    return float(np.hypot((lat1 - lat2) * 111.0, (lon1 - lon2) * 111.0 * np.cos(np.radians((lat1 + lat2) / 2))))


def odds(p) -> str:
    try:
        p = float(p)
    except (TypeError, ValueError):
        return "unknown"
    if p <= 0:
        return "close to zero"
    if p < 0.5:
        return f"about 1 in {max(2, round(1 / p))}"
    return f"about {round(p * 10)} in 10"


def names_list(names: list[str]) -> str:
    names = [short(n) for n in names]
    return names[0] if len(names) == 1 else ", ".join(names[:-1]) + " and " + names[-1]


def _assets(rp) -> list[dict]:
    return [a for a in (rp or {}).get("assets") or [] if isinstance(a, dict)]


def truth_mm(rp) -> float:
    try:
        return float(((rp or {}).get("thresholds") or {}).get("truth_mm", HIT_MM_DEFAULT))
    except (TypeError, ValueError):
        return HIT_MM_DEFAULT


def hit_time(a: dict, thr: float):
    o = a.get("observed") or {}
    mx = o.get("max_mesh_mm")
    if o.get("first_ge30_time") and mx is not None and float(mx) >= thr:
        return data.to_mdt(o["first_ge30_time"])
    return None


def site_status(a: dict, issue: str, thr: float) -> str:
    """Raw status key for the map dot at this issue time."""
    t = data.to_mdt(issue)
    ht = hit_time(a, thr)
    if ht is not None and t is not None and ht <= t:
        return "HIT"
    r = asset_state_at(a, issue)
    if r.get("task_window_status") == "BLOCKED_UNSAFE":
        return "BLOCKED_UNSAFE"
    s = str(r.get("state") or "").upper()
    return s if s in ("WATCH", "ARM", "TRIGGER") else "ALL_CLEAR"


# ---------- the feed ----------

@dataclass
class Item:
    t: pd.Timestamp
    text: str
    official: bool = False
    who: str = ""
    order: int = 0
    tags: set = field(default_factory=set)


def _group_phrase(group: list[dict]) -> str:
    """'Country Hills Toyota' or '5 businesses near the airport'."""
    if len(group) <= INLINE_NAMES:
        return names_list([a.get("name") for a in group])
    near = all(km(a["lat"], a["lon"], *AIRPORT) <= NEAR_AIRPORT_KM for a in group
               if a.get("lat") is not None and a.get("lon") is not None)
    return f"{len(group)} businesses" + (" near the airport" if near else "")


def _minutes_phrase(mins: list[float]) -> str:
    m = sorted(int(5 * round(x / 5)) for x in mins if x is not None and np.isfinite(x))
    if not m:
        return "soon"
    lo, hi = max(m[0], 5), max(m[-1], 5)
    return f"about {lo} minutes" if lo == hi else f"about {lo} to {hi} minutes"


def site_events(rp: dict) -> list[tuple]:
    """(time, kind, asset, extra) milestones per site: ready / act / shelter / clear / hit. No flicker:
    each kind fires once per warning episode; an ALL_CLEAR ends the episode."""
    thr = truth_mm(rp)
    out = []
    for a in _assets(rp):
        rows = sorted([r for r in a.get("timeline") or [] if isinstance(r, dict) and data.to_mdt(r.get("issue_time"))],
                      key=lambda r: data.to_mdt(r["issue_time"]))
        warned = sheltered = acted = watched = False
        for r in rows:
            t = data.to_mdt(r["issue_time"])
            s = str(r.get("state") or "").upper()
            blocked = r.get("task_window_status") == "BLOCKED_UNSAFE"
            if s == "WATCH" and not (watched or warned):
                watched = True
                lead = r.get("watch_arrival_earliest_lead_min")
                if lead is None:
                    arr = data.to_mdt(r.get("watch_arrival_earliest") or r.get("arrival_earliest"))
                    lead = (arr - t).total_seconds() / 60 if arr is not None else None
                out.append((t, "watch", a, lead))
            if s in ("ARM", "TRIGGER") and not warned:
                warned = True
                if not blocked and s == "ARM":
                    arr = data.to_mdt(r.get("arrival_likely"))
                    mins = (arr - t).total_seconds() / 60 if arr is not None else None
                    out.append((t, "ready", a, mins))
            if warned and blocked and not sheltered:
                sheltered = acted = True
                out.append((t, "shelter" if hit_time(a, thr) is not None else "nearby", a, None))
            elif warned and s == "TRIGGER" and not acted:
                acted = True
                out.append((t, "act", a, None))
            if (warned or watched) and s in ("ALL_CLEAR", "MONITOR") and not blocked:
                if warned or s == "ALL_CLEAR":
                    out.append((t, "clear" if hit_time(a, thr) is not None else "missed", a, None))
                    warned = sheltered = acted = watched = False
        ht = hit_time(a, thr)
        if ht is not None:
            out.append((ht, "hit", a, (a.get("observed") or {}).get("max_mesh_mm")))
    return out


KIND_ORDER = {"hit": 0, "shelter": 1, "nearby": 2, "act": 3, "ready": 4, "watch": 5, "missed": 6, "clear": 7}
KIND_STATE = {"watch": "WATCH", "ready": "ARM", "act": "TRIGGER", "shelter": "BLOCKED_UNSAFE", "nearby": "BLOCKED_UNSAFE",
              "clear": "ALL_CLEAR", "missed": "ALL_CLEAR", "hit": "HIT"}


def _clause(kind: str, group: list[dict], extras: list, rp: dict) -> str:
    who = _group_phrase(group)
    if kind == "watch":
        when = _minutes_phrase(extras)
        when = "within the next hour or so" if when == "soon" else f"in {when}"
        return f"{who}: a storm is approaching and could reach you {when}. Start the big jobs now."
    if kind == "ready":
        return f"{who}: hail likely in {_minutes_phrase(extras)}. Get ready."
    if kind == "act":
        return f"{who}: hail is coming. Act now — start protecting."
    if kind == "shelter":
        return f"{who}: hail is minutes away — stop outdoor work and get inside."
    if kind == "nearby":
        return f"{who}: storm passing close by — stay indoors for now (lightning)."
    if kind == "clear":
        return f"{who}: the storm has passed. All clear."
    if kind == "missed":
        return f"{who}: the storm passed — the hail missed you. All clear."
    if kind == "hit":
        mx = max(float(x) for x in extras if x is not None)
        per = ((rp.get("evaluation") or {}).get("nowcast") or {}).get("per_asset") or {}
        warned = sum(1 for a in group if (per.get(a.get("asset_id")) or {}).get("lead_min") is not None)
        if len(group) == 1:
            tail = " It had been warned." if warned else " It had not been warned."
        elif len(group) == 2:
            tail = " Both had been warned." if warned == 2 else f" {warned} of 2 had been warned."
        else:
            tail = (f" All {len(group)} had been warned." if warned == len(group)
                    else f" {warned} of {len(group)} had been warned.")
        return f"Hail hit {who} (up to {mx:.0f} mm, {size_words(mx)}).{tail}"
    return who


def build_feed(rp: dict | None, ec: dict | None, sc: dict | None) -> list[Item]:
    """Whole-evening feed, oldest first. Callers filter by time and reverse."""
    items: list[Item] = []
    day = pd.Timestamp((rp or {}).get("event") or (sc or {}).get("date") or EVENT)
    # 1. morning outlook (06:00 local issue)
    if sc:
        t6 = pd.Timestamp(f"{day.date()} 06:00").tz_localize("America/Edmonton")
        state = str(sc.get("state_day") or "MONITOR").upper()
        p = sc.get("p_day")
        if state == "PREPARE":
            text = (f"Morning heads-up: today could be a hail day ({odds(p)} chance). Keep crew on standby.")
        else:
            text = f"Morning outlook: hail unlikely today ({odds(p)} chance)."
        hits = [a for a in _assets(rp) if hit_time(a, truth_mm(rp)) is not None]
        if hits and state != "PREPARE":
            text += " Our morning forecast missed this storm."
        items.append(Item(t6, text, order=-1))
    # 2. official warnings: first one covering Calgary, then each change in severity
    last_sev = None
    for e in sorted([e for e in (ec or {}).get("timeline") or [] if isinstance(e, dict) and e.get("covers_calgary")],
                    key=lambda e: str(e.get("time_mdt"))):
        t = data.to_mdt(e.get("time_mdt"))
        sev = e.get("severity")
        if t is None or sev == last_sev:
            continue
        hail = e.get("hail_wording")
        if last_sev is None:
            text = "Government warning (Environment Canada): severe thunderstorm warning for all of Calgary."
        elif "alert ready" in str(e.get("product", "")).lower():
            text = ("Government warning upgraded (Environment Canada): emergency alert sent to every phone "
                    "in Calgary.")
        else:
            text = f"Government warning updated (Environment Canada): {str(e.get('product', 'update')).lower()}."
        if hail:
            text += f" Expected hail: {hail} size."
        items.append(Item(t, text, official=True))
        last_sev = sev
    # 3. HailTech's per-business messages, grouped by time: one line per moment
    ev = site_events(rp or {})
    by_t: dict = {}
    for t, kind, a, extra in ev:
        by_t.setdefault(t, {}).setdefault(kind, []).append((a, extra))
    for t, kinds in by_t.items():
        clauses, who = [], []
        for kind in sorted(kinds, key=lambda k: KIND_ORDER.get(k, 9)):
            grp = [a for a, _ in kinds[kind]]
            clauses.append(_clause(kind, grp, [x for _, x in kinds[kind]], rp))
            if len(grp) > INLINE_NAMES:
                who.append(f"{ui.plain(KIND_STATE.get(kind, kind))}: " + names_list([a.get("name") for a in grp]))
        items.append(Item(t, " ".join(clauses), who=" · ".join(who), tags=set(kinds)))
    # 4. close of the evening: who never had to move
    issues = [data.to_mdt(x) for x in (rp or {}).get("issue_times") or []]
    issues = [x for x in issues if x is not None]
    if issues and rp:
        per = ((rp.get("evaluation") or {}).get("nowcast") or {}).get("per_asset") or {}
        thr = truth_mm(rp)
        never = [a for a in _assets(rp) if not (per.get(a.get("asset_id")) or {}).get("first_arm")]
        stood = [a for a in never if hit_time(a, thr) is None]
        missed = [a for a in never if hit_time(a, thr) is not None]
        text = (f"Evening wrap-up: {len(stood)} businesses were never asked to do anything, and hail missed every "
                "one of them — they could stand down all evening.") if stood and not missed else \
               (f"Evening wrap-up: {len(stood)} businesses were never asked to act; "
                f"{len(missed)} business(es) were hit without a warning.")
        items.append(Item(max(issues), text, who="Never asked to act: " + names_list([a.get("name") for a in stood])
                          if stood else ""))
    items.sort(key=lambda i: (i.t, i.order, not i.official))
    return items


def feed_text(items: list[Item]) -> str:
    """Plain text of the feed (oldest first), for reports and tests."""
    return "\n".join(f"{clock(i.t)} — {i.text}" + (f"\n        ({i.who})" if i.who else "") for i in items)


# ---------- numbers, table ----------

def headline_numbers(rp: dict):
    ev = rp.get("evaluation") or {}
    nc = ev.get("nowcast_watch") or ev.get("nowcast") or {}
    per = (ev.get("nowcast") or {}).get("per_asset") or {}
    thr = truth_mm(rp)
    fa_sites = [a for a in _assets(rp) if (per.get(a.get("asset_id")) or {}).get("first_arm")
                and hit_time(a, thr) is None]
    return nc, per, fa_sites


def false_alarm_edge_km(rp: dict, fields: dict | None, fa_sites: list[dict]):
    """Largest distance (km) from a false-alarm site to anywhere radar saw damaging hail; None if unknown."""
    obs = (fields or {}).get("obs_mesh")
    if obs is None or getattr(obs, "ndim", 0) != 3 or not fa_sites:
        return None
    lats, lons = grid_axes(rp, fields, obs.shape[1], obs.shape[2])
    if lats is None or lons is None:
        return None
    iy, ix = np.where(np.nanmax(obs, axis=0) >= truth_mm(rp))
    if iy.size == 0:
        return None
    pl, po = lats[iy], lons[ix]
    d = [float(np.min(np.hypot((pl - a["lat"]) * 111.0, (po - a["lon"]) * 111.0 * np.cos(np.radians(a["lat"])))))
         for a in fa_sites if a.get("lat") is not None]
    return max(d) if d else None


def _nearest_hail_km(a: dict, rp: dict, fields: dict | None):
    """Distance (km) from a site to the closest place radar saw hail >= the hit size that evening."""
    obs = (fields or {}).get("obs_mesh")
    if obs is None or getattr(obs, "ndim", 0) != 3 or a.get("lat") is None:
        return None
    lats, lons = grid_axes(rp, fields, obs.shape[1], obs.shape[2])
    if lats is None or lons is None:
        return None
    iy, ix = np.where(np.nanmax(obs, axis=0) >= truth_mm(rp))
    if iy.size == 0:
        return None
    return float(np.min(np.hypot((lats[iy] - a["lat"]) * 111.0,
                                 (lons[ix] - a["lon"]) * 111.0 * np.cos(np.radians(a["lat"])))))


def _mins_between(t0, t1):
    a, b = data.to_mdt(t0), data.to_mdt(t1)
    return None if a is None or b is None else (b - a).total_seconds() / 60


def _table(cols: list[str], rows: list[dict]) -> str:
    head = "".join(f"<th>{html.escape(c)}</th>" for c in cols)
    body = "".join("<tr>" + "".join(f"<td>{html.escape(str(r.get(c, '')))}</td>" for c in cols) + "</tr>"
                   for r in rows)
    return f'<table class="hd-tab"><thead><tr>{head}</tr></thead><tbody>{body}</tbody></table>'


def who_tables(rp: dict, fields: dict | None) -> list[tuple[str, str, str]]:
    """(heading, one-line explanation, html table) for: hit and warned, hit and not warned, false alarms, stood down."""
    per = ((rp.get("evaluation") or {}).get("nowcast") or {}).get("per_asset") or {}
    hit_warned, hit_missed, false_alarm, stood_down = [], [], [], []
    for a in sorted(_assets(rp), key=lambda x: short(x.get("name"))):
        p = per.get(a.get("asset_id")) or {}
        task = a.get("task") or {}
        first = task.get("first_alert") or p.get("first_arm")
        warned = bool(first)
        hit = hit_time(a, truth_mm(rp)) is not None
        mx = float((a.get("observed") or {}).get("max_mesh_mm") or 0)
        kind = CATEGORY.get(a.get("category"), str(a.get("category", "-")))
        if hit and warned:
            job = task.get("task_duration_min")
            lead = task.get("alert_lead_min", p.get("lead_min"))
            safe = task.get("safe_minutes")
            if safe is None:
                safe = _mins_between(first, task.get("first_blocked_issue")) if task.get("first_blocked_issue") else lead
            if job is None or safe is None:
                verdict = "-"
            elif safe >= job:
                verdict = f"Yes: {safe:.0f} min of safe working time for a {job:.0f}-min job"
            elif safe >= job / 2:
                verdict = f"Partly: {safe:.0f} min of safe working time for a {job:.0f}-min job"
            else:
                verdict = f"No: only {safe:.0f} min of safe working time for a {job:.0f}-min job"
            hit_warned.append({"Business": short(a.get("name")), "Type": kind,
                               "Warned": f"{clock(first)} ({lead:.0f} min before the hail)"
                               if isinstance(lead, (int, float)) else clock(first),
                               "Staff had to get inside": clock(task.get("first_blocked_issue"))
                               if task.get("first_blocked_issue") else "-",
                               "Hail size": f"{mx:.0f} mm ({size_words(mx)})",
                               "Could they finish protecting in time?": verdict})
        elif hit:
            hit_missed.append({"Business": short(a.get("name")), "Type": kind,
                               "Hail size": f"{mx:.0f} mm ({size_words(mx)})"})
        elif warned:
            d = _nearest_hail_km(a, rp, fields)
            false_alarm.append({"Business": short(a.get("name")), "Type": kind, "Warned": clock(first),
                                "What actually fell here": f"{mx:.0f} mm ({size_words(mx)})" if mx >= 5
                                else "little or no hail",
                                "Damaging hail came within": f"{d:.0f} km" if d is not None else "-"})
        else:
            stood_down.append({"Business": short(a.get("name")), "Type": kind})
    out = [("Hit by hail, and warned first",
            "Safe working time runs from the first warning until the storm got close enough that staff had to "
            "get inside. Job lengths are our estimates.",
            _table(["Business", "Type", "Warned", "Staff had to get inside", "Hail size",
                    "Could they finish protecting in time?"], hit_warned))]
    if hit_missed:
        out.append(("Hit by hail, but NOT warned", "HailTech missed these.",
                    _table(["Business", "Type", "Hail size"], hit_missed)))
    out.append(("Warned, but the hail missed them (false alarms)",
                "The storm passed close by, so these businesses were warned and later told to stay indoors "
                "as a lightning precaution. The damaging hail fell a few kilometres away.",
                _table(["Business", "Type", "Warned", "What actually fell here", "Damaging hail came within"],
                       false_alarm)))
    out.append((f"Correctly left alone ({len(stood_down)} businesses)",
                "Never warned, and the hail missed every one of them: no wasted effort.",
                _table(["Business", "Type"], stood_down)))
    return out


# ---------- page ----------

def _advance(key_idx: str, n: int):
    if st.session_state.pop("sy_advance", False):
        nxt = int(st.session_state.get(key_idx, 0)) + 1
        if nxt >= n:
            st.session_state["sy_playing"] = False
            nxt = n - 1
        st.session_state[key_idx] = nxt


def _render_feed(items: list[Item], issue: str):
    t = data.to_mdt(issue)
    shown = [i for i in items if t is None or i.t <= t][::-1]
    prev_t = t - pd.Timedelta(minutes=6) if t is not None else None
    parts = []
    for i in shown:
        cls = "it official" if i.official else "it"
        if prev_t is not None and i.t > prev_t:
            cls += " new"
        tag = '<span class="tag">OFFICIAL</span>' if i.official else ""
        who = f'<div class="who">{html.escape(i.who, quote=False)}</div>' if i.who else ""
        parts.append(f'<div class="{cls}">{tag}<b class="t">{clock(i.t)}</b> {html.escape(i.text, quote=False)}{who}</div>')
    if not parts:
        parts.append('<div class="it">Nothing yet.</div>')
    st.markdown('<div class="hd-feed">' + "".join(parts) + "</div>", unsafe_allow_html=True)


def render():
    st.title(TITLE)
    rp, fields = data.replay(EVENT)
    if rp is None:
        st.info("The storm replay files for 5 August 2024 are not on this computer yet, so this story can't be "
                "shown. The other pages in the sidebar still work.")
        return
    ui.fixture_banner(f"nowcast/replay_{EVENT}.json")
    assets = _assets(rp)
    st.markdown(f'<p class="hd-lede">On 5 August 2024 a hailstorm did about $3 billion of damage in north Calgary '
                f"in under an hour. Here's what HailTech would have told {len(assets)} real Calgary businesses.</p>",
                unsafe_allow_html=True)

    # --- three big numbers ---
    nc, per, fa_sites = headline_numbers(rp)
    edge = false_alarm_edge_km(rp, fields, fa_sites)
    c1, c2, c3 = st.columns(3)
    if nc.get("hits_total") is not None:
        c1.markdown(f'<p class="hd-stat">{nc.get("hits_caught", 0)} of {nc["hits_total"]}</p>'
                    '<div class="hd-stat-sub">businesses that got hit were warned first</div>',
                    unsafe_allow_html=True)
    if isinstance(nc.get("median_lead_min"), (int, float)):
        c2.markdown(f'<p class="hd-stat">about {nc["median_lead_min"]:.0f} min</p>'
                    '<div class="hd-stat-sub">of warning before the hail (typical business)</div>',
                    unsafe_allow_html=True)
    if nc.get("false_alarms") is not None:
        fa = int(nc["false_alarms"])
        sub = (f"all near the storm's edge (within {edge:.0f} km of damaging hail)"
               if edge is not None and edge <= EDGE_KM and fa else "warned, but the hail missed them")
        c3.markdown(f'<p class="hd-stat">{fa} false alarm{"s" if fa != 1 else ""}</p>'
                    f'<div class="hd-stat-sub">{html.escape(sub, quote=False)}</div>', unsafe_allow_html=True)
    if not nc:
        st.info("The scorecard for this storm hasn't been computed yet.")

    # --- time controls ---
    issues = [str(x) for x in rp.get("issue_times") or []]
    n = len(issues)
    key_idx = "sy_idx"
    st.session_state.setdefault(key_idx, 0)
    st.session_state.setdefault("sy_playing", False)
    _advance(key_idx, n)
    if st.session_state[key_idx] >= n:
        st.session_state[key_idx] = n - 1

    def toggle():
        playing = not st.session_state.get("sy_playing", False)
        if playing and st.session_state.get(key_idx, 0) >= n - 1:
            st.session_state[key_idx] = 0
        st.session_state["sy_playing"] = playing

    b1, b2 = st.columns([0.9, 6])
    b1.button("Pause" if st.session_state["sy_playing"] else "▶ Play the evening", on_click=toggle,
              width="stretch", key="sy_play", type="primary")
    with b2:
        if n > 1:
            st.select_slider("Time on 5 August (Calgary time)", options=list(range(n)), key=key_idx,
                             format_func=lambda k: clock(issues[k]), label_visibility="collapsed")
    i = int(st.session_state[key_idx])
    issue = issues[i]
    thr = truth_mm(rp)

    # --- map + feed ---
    layers = []
    obs = fields.get("obs_mesh") if fields else None
    fi = i
    if fields is not None and "issue_times" in fields:
        ft = [str(x) for x in np.asarray(fields["issue_times"]).ravel()]
        fi = ft.index(issue) if issue in ft else (i if i < len(ft) else None)
    if obs is not None and getattr(obs, "ndim", 0) == 3 and fi is not None and fi < obs.shape[0]:
        lats, lons = grid_axes(rp, fields, obs.shape[1], obs.shape[2])
        layers.append(bitmap_layer(np.nanmax(obs[:fi + 1], axis=0), lats, lons, PAST_STOPS, "past"))
        layers.append(bitmap_layer(obs[fi], lats, lons, MESH_STOPS, "now"))
    layers = [l for l in layers if l is not None]

    pts = []
    for a in assets:
        if a.get("lat") is None or a.get("lon") is None:
            continue
        s = site_status(a, issue, thr)
        mx = (a.get("observed") or {}).get("max_mesh_mm")
        pts.append({"lat": a["lat"], "lon": a["lon"], "name": short(a.get("name")),
                    "type": CATEGORY.get(a.get("category"), ""), "status": ui.plain(s),
                    "color": ui.STORY_RGB.get(s, ui.STORY_GREY),
                    "line": [255, 255, 255] if s != "HIT" else [255, 210, 0],
                    "size": "" if s != "HIT" else f"Hail up to {float(mx):.0f} mm ({size_words(mx)})"})
    if pts:
        layers.append(pdk.Layer("ScatterplotLayer", pd.DataFrame(pts), get_position="[lon, lat]",
                                get_fill_color="color", get_line_color="line", get_radius=600,
                                radius_min_pixels=11, radius_max_pixels=26, stroked=True,
                                line_width_min_pixels=3, pickable=True))
    tip = {"html": "<b>{name}</b><br/>{type}<br/><b>{status}</b><br/>{size}", "style": {"fontSize": "16px"}}

    mc, fc = st.columns([1.55, 1])
    with mc:
        st.markdown(f"### {clock(issue)}")
        ui.deck(layers, tooltip=tip, view=VIEW, height=560)
        ui.legend([("All clear", ui.STORY_RGB["ALL_CLEAR"]), ("Get ready", ui.STORY_RGB["ARM"]),
                   ("Act now", ui.STORY_RGB["TRIGGER"]), ("Take shelter", ui.STORY_RGB["BLOCKED_UNSAFE"]),
                   ("Hail hit here", ui.STORY_RGB["HIT"])])
        st.caption("Coloured shading = hail falling right now (yellow small, red big), from radar. "
                   "Faint brown = where hail has already fallen this evening. Dots = the businesses.")
        if fields is None:
            st.caption("Radar picture not available on this computer; showing businesses only.")
    with fc:
        st.markdown("### What HailTech said")
        items = build_feed(rp, eccc_warnings(EVENT), data.scores(EVENT))
        with st.container(height=560, border=False):
            _render_feed(items, issue)

    # --- who was warned ---
    st.subheader("Who was warned?")
    tabs = who_tables(rp, fields)
    for heading, why, tab in tabs:
        st.markdown(f"**{heading}**")
        st.caption(why)
        st.markdown(tab, unsafe_allow_html=True)
    st.caption(f"Hail sizes come from radar (the largest seen at each business that evening). A business counts as "
               f"hit when radar showed hail of {thr:.0f} mm or more there.")

    # --- why this matters ---
    never = sum(1 for a in assets if not (per.get(a.get("asset_id")) or {}).get("first_arm")
                and hit_time(a, thr) is None)
    st.subheader("Why this matters")
    st.markdown(
        "- **The government warns the whole city; HailTech tells each business if it's them.**\n"
        f"- **It says which businesses can stand down:** {never} here were never asked to act, and hail missed "
        "them all.\n"
        "- **It never tells anyone to go outside in a storm, and official warnings always come first.**")

    with st.expander("How do we know?"):
        st.markdown(
            "- We replayed the evening using **only the data that was available at each moment** — no peeking "
            "ahead.\n"
            "- Hail measurements come from **NOAA weather radar** (hail size from radar).\n"
            "- We checked against **independent damage surveys** from Western University's **Northern Hail "
            "Project** (used under a non-commercial licence).\n"
            "- Costs and how long each protective job takes are **our estimates**, not figures from the businesses.")

    if st.session_state.get("sy_playing"):
        if i >= n - 1:
            st.session_state["sy_playing"] = False
            st.rerun()
        else:
            t0, t1 = data.to_mdt(issues[i]), data.to_mdt(issues[i + 1])
            busy = any(t0 < it.t <= t1 for it in items) if t0 is not None and t1 is not None else False
            time.sleep(PLAY_SLOW_S if busy else PLAY_FAST_S)
            st.session_state["sy_advance"] = True
            st.rerun()
