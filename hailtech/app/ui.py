"""Shared UI helpers: projector-friendly styling, map defaults, colours, empty states."""
from __future__ import annotations

import pydeck as pdk
import streamlit as st

import data

CALGARY = dict(latitude=51.05, longitude=-114.07, zoom=9.6, pitch=0, bearing=0)
BASEMAP = "https://basemaps.cartocdn.com/gl/positron-gl-style/style.json"   # CARTO light, no token

# Colours (RGB). Chosen for contrast on a projector and red/green-safe pairing with shape/labels.
RED = [200, 30, 45]
AMBER = [235, 140, 0]
BLUE = [30, 100, 200]
GREY = [120, 120, 120]
GREEN = [20, 140, 90]
LIGHT = [185, 185, 185]
STATE_RGB = {"TRIGGER": RED, "ARM": AMBER, "PREPARE": AMBER, "MONITOR": BLUE, "WATCH": BLUE,
             "ALL_CLEAR": GREEN, "CLEAR": GREEN, "DATA_DEGRADED": LIGHT, "NONE": GREY}
STATE_ORDER = ["DATA_DEGRADED", "ALL_CLEAR", "CLEAR", "MONITOR", "ARM", "TRIGGER"]
STATE_HEX = {k: "#%02x%02x%02x" % tuple(v) for k, v in STATE_RGB.items()}

# ---------- plain words (labels only; data keeps the raw state names) ----------
PLAIN = {"ARM": "Get ready", "TRIGGER": "Act now", "BLOCKED_UNSAFE": "Take shelter", "ALL_CLEAR": "All clear",
         "CLEAR": "All clear", "MONITOR": "Watching", "WATCH": "Storm approaching", "PREPARE": "Heads-up",
         "CANCEL": "Stand down", "PROTECT": "Protect", "DATA_DEGRADED": "Radar data patchy", "NONE": "No data",
         "HIT": "Hail hit here", "MESH": "hail size from radar"}
TASK_PLAIN = {"FEASIBLE": "Yes", "TIGHT": "Just barely", "MISSED": "No \u2014 needed the morning heads-up",
              "BLOCKED_UNSAFE": "Too dangerous to go outside", "NOT_NEEDED": "Not needed"}
# Story-page dot colours: chosen to stay distinct on a washed-out projector.
PURPLE = [120, 40, 170]
DARK_RED = [95, 0, 15]
STORY_GREY = [140, 140, 140]
STORY_RGB = {"ALL_CLEAR": STORY_GREY, "ARM": AMBER, "TRIGGER": [225, 30, 40], "BLOCKED_UNSAFE": PURPLE,
             "HIT": DARK_RED}


def plain(state) -> str:
    """Raw decision/task state -> plain words for screens. Unknown values pass through unchanged."""
    k = str(state or "").upper()
    return PLAIN.get(k) or TASK_PLAIN.get(k) or str(state or "-")

CSS = """
<style>
html, body, [class*="css"] { font-size: 18px; }
div[data-testid="stMetricValue"] { font-size: 3.0rem; font-weight: 700; }
div[data-testid="stMetricLabel"] p { font-size: 1.05rem; font-weight: 600; }
.hd-big { font-size: 4.2rem; font-weight: 800; line-height: 1.0; margin: 0; }
.hd-badge { display:inline-block; padding: 0.35rem 1.0rem; border-radius: 0.5rem; color: white;
            font-weight: 800; font-size: 1.6rem; letter-spacing: 0.05em; }
.hd-sub { color: #555; font-size: 1.0rem; margin-top: 0.2rem; }
.hd-legend span { display:inline-block; margin-right: 1.2rem; font-size: 1.0rem; }
.hd-stat { font-size: 3.6rem; font-weight: 800; line-height: 1.05; margin: 0; color: #111; }
.hd-stat-sub { font-size: 1.15rem; color: #333; font-weight: 600; }
.hd-lede { font-size: 1.45rem; line-height: 1.45; color: #222; }
.hd-feed { font-size: 1.15rem; line-height: 1.4; }
.hd-feed .it { padding: 0.55rem 0.75rem; margin-bottom: 0.45rem; border-left: 0.45rem solid #999;
               background: #f6f6f6; border-radius: 0.3rem; color: #111; }
.hd-feed .it b.t { display:inline-block; min-width: 5.2rem; }
.hd-feed .who { font-size: 0.95rem; color: #444; margin-top: 0.15rem; }
.hd-feed .official { background: #fff4d6; border: 2px solid #8a5a00; border-left: 0.45rem solid #8a5a00; }
.hd-feed .official .tag { display:inline-block; background:#8a5a00; color:white; font-size:0.8rem; font-weight:800;
                          padding: 0.05rem 0.45rem; border-radius: 0.25rem; margin-right: 0.4rem; letter-spacing: 0.04em; }
.hd-feed .new { box-shadow: 0 0 0 3px #1f4fd1; }
table.hd-tab { border-collapse: collapse; width: 100%; font-size: 1.05rem; }
table.hd-tab th { text-align: left; background: #222; color: white; padding: 0.4rem 0.6rem; }
table.hd-tab td { padding: 0.35rem 0.6rem; border-bottom: 1px solid #ddd; color: #111; }
table.hd-tab tr.hit td { background: #fbe9ea; }
/* sidebar: heading above the judges' detail pages (radio options 2..n) */
section[data-testid="stSidebar"] div[role="radiogroup"] > label:first-child p { font-weight: 800; font-size: 1.1rem; }
section[data-testid="stSidebar"] div[role="radiogroup"] > label:nth-child(2) { margin-top: 2.1rem; position: relative; }
section[data-testid="stSidebar"] div[role="radiogroup"] > label:nth-child(2)::before {
  content: "Details for judges"; position: absolute; top: -1.8rem; left: 0; font-weight: 700; font-size: 0.95rem;
  color: #555; text-transform: uppercase; letter-spacing: 0.05em; white-space: nowrap; }
.hd-dot { display:inline-block; width: 0.9rem; height: 0.9rem; border-radius: 50%; margin-right: 0.35rem;
          vertical-align: middle; }
</style>
"""


def style():
    st.markdown(CSS, unsafe_allow_html=True)


def not_computed(what: str, files: str, hint: str = ""):
    msg = f"**{what}: not yet computed.** Waiting for `{files}`."
    if hint:
        msg += f"  \n{hint}"
    if not data.fixtures_enabled():
        msg += "  \n_Developers: set `HAILDAY_FIXTURES=1` to preview this panel with synthetic fixture data._"
    st.info(msg)


def fixture_banner(*rels):
    if any(data.is_fixture(data.resolve(r)) for r in rels):
        st.warning("FIXTURE DATA: this panel is showing synthetic development data, not pipeline output.")


def badge(text: str, rgb) -> str:
    return f'<span class="hd-badge" style="background: rgb({rgb[0]},{rgb[1]},{rgb[2]})">{text}</span>'


def legend(items):
    parts = [f'<span><span class="hd-dot" style="background: rgb({c[0]},{c[1]},{c[2]})"></span>{label}</span>'
             for label, c in items]
    st.markdown('<div class="hd-legend">' + "".join(parts) + "</div>", unsafe_allow_html=True)


def deck(layers, tooltip=None, view=None, height=520):
    v = pdk.ViewState(**(view or CALGARY))
    d = pdk.Deck(layers=layers, initial_view_state=v, map_style=BASEMAP, map_provider="carto",
                 tooltip=tooltip or False)
    st.pydeck_chart(d, height=height, width="stretch")


def money(x) -> str:
    try:
        x = float(x)
    except (TypeError, ValueError):
        return "-"
    a = abs(x)
    s = "-" if x < 0 else ""
    if a >= 1e9:
        return f"{s}${a / 1e9:.2f}B"
    if a >= 1e6:
        return f"{s}${a / 1e6:.2f}M"
    if a >= 1e4:
        return f"{s}${a / 1e3:.0f}k"
    return f"{s}${a:,.0f}"


def pct(x, digits=0) -> str:
    try:
        return f"{100 * float(x):.{digits}f}%"
    except (TypeError, ValueError):
        return "-"
