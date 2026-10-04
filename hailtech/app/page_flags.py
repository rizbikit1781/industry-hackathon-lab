"""Page D: Community flags (Case 4). Flag = P(day) >= p_cut AND exposure >= e_cut."""
from __future__ import annotations

import numpy as np
import pandas as pd
import pydeck as pdk
import streamlit as st

import data
import page_briefing
import ui

DOWNTOWN = {"DOWNTOWN COMMERCIAL CORE", "DOWNTOWN EAST VILLAGE", "DOWNTOWN WEST END", "EAU CLAIRE", "CHINATOWN",
            "BELTLINE"}


def flags(df: pd.DataFrame, p_day: float, p_cut: float, e_cut: float) -> pd.Series:
    return (p_day >= p_cut) & (df["exposure"] >= e_cut)


def flip_count(current: frozenset, key: str) -> tuple[int, list[str]]:
    """Symmetric difference vs the previous distinct flag set held in session_state."""
    last = st.session_state.get(f"{key}_last")
    if last is None:
        st.session_state[f"{key}_last"] = current
        st.session_state[f"{key}_flips"] = (0, [])
    elif last != current:
        diff = sorted(last ^ current)
        st.session_state[f"{key}_flips"] = (len(diff), diff)
        st.session_state[f"{key}_last"] = current
    return st.session_state.get(f"{key}_flips", (0, []))


def summary(date, p_day, p_cut, e_cut, df, n_flag, n_dt, n_city, flips) -> str:
    top = df[df["flag"]].sort_values("exposure", ascending=False)["community_name"].head(5).str.title().tolist()
    sect = ""
    if "sector" in df.columns and n_flag:
        s = df[df["flag"]]["sector"].value_counts()
        sect = ", ".join(f"{k.title()} {v}" for k, v in s.head(3).items())
    lines = [
        f"**Community hail flags for {page_briefing.date_label(date)}.**",
        f"Regional hail-day probability {ui.pct(p_day)}; flag cutoff {ui.pct(p_cut)} on probability and "
        f"{e_cut:.2f} on historical exposure.",
        (f"**{n_flag} of {len(df)} communities flagged**" + (f" (by sector: {sect})." if sect else ".")) if n_flag
        else f"No communities flagged ({'probability below cutoff' if p_day < p_cut else 'no community above the exposure cutoff'}).",
    ]
    if top:
        lines.append("Highest exposure among flagged: " + ", ".join(top) + ".")
    lines.append(f"Baselines: downtown-only would flag {n_dt}; citywide-if-high would flag {n_city}.")
    if flips[0]:
        lines.append(f"Last cutoff change flipped {flips[0]} communities.")
    lines.append("Exposure is historical radar hail frequency, not a forecast of where today's storm will go.")
    return "  \n".join(lines)


def render():
    st.title("Community flags")
    st.caption("Case 4 compliance view. Flag a community when P(regional hail day) >= p_cut AND its historical "
               "hail exposure >= e_cut. Compare against the case's two baselines.")
    d = page_briefing.pick_date("flags")
    expo, how = data.exposure()
    if expo is None:
        ui.not_computed("Community exposure", "data/processed/exposure.parquet or mesh_hit_rates.npz")
        return
    p_day = None
    if d is not None:
        sc = data.scores(d)
        try:
            p_day = float((sc or {}).get("p_day"))
        except (TypeError, ValueError):
            p_day = None
        ui.fixture_banner(f"scores/{d}.json", "exposure.parquet")
    if p_day is None:
        ui.not_computed("Regional probability for this date", "data/processed/scores/<YYYY-MM-DD>.json",
                        "Using a manual what-if probability below.")
    if p_day is None or st.toggle("What-if: set P(regional hail day) by hand", key="fl_whatif"):
        p_day = st.slider("What-if P(regional hail day)", 0.0, 1.0, 0.5 if p_day is None else round(p_day, 2), 0.01,
                          key="fl_pday")
    d = d or "what-if"

    df = expo.copy()
    df["community_name"] = df["community_name"].astype(str)
    df["exposure"] = pd.to_numeric(df["exposure"], errors="coerce").fillna(0.0).clip(0, 1)
    comm = data.communities()
    if comm is not None and "sector" not in df.columns and "community_name" in comm.columns:
        df = df.merge(comm[["community_name"] + [c for c in ("sector", "hail_track") if c in comm.columns]],
                      on="community_name", how="left")

    c1, c2, c3 = st.columns([1, 1, 1])
    p_cut = c1.slider("p_cut: probability cutoff", 0.0, 1.0, 0.30, 0.05, key="fl_p")
    e_cut = c2.slider("e_cut: exposure cutoff", 0.0, 1.0, 0.50, 0.05, key="fl_e")
    with c3:
        st.metric("P(regional hail day)", ui.pct(p_day))

    df["flag"] = flags(df, p_day, p_cut, e_cut)
    df["downtown"] = df["community_name"].str.upper().isin(DOWNTOWN)
    n_flag = int(df["flag"].sum())
    n_dt = int(df["downtown"].sum()) if p_day >= p_cut else 0
    n_city = len(df) if p_day >= p_cut else 0
    flips = flip_count(frozenset(df.loc[df["flag"], "community_name"]), f"fl_{d}")

    m1, m2, m3, m4 = st.columns(4)
    m1.metric("HailTech flags", f"{n_flag} / {len(df)}")
    m2.metric("Flipped by last change", flips[0])
    m3.metric("Baseline: downtown only", n_dt)
    m4.metric("Baseline: citywide if high", n_city)

    left, right = st.columns([1.7, 1])
    with left:
        m = df.copy()
        m["color"] = [ui.RED + [220] if f else ([30, 100, 200, int(60 + 150 * e)]) for f, e in zip(m["flag"], m["exposure"])]
        m["status"] = np.where(m["flag"], "FLAGGED", "not flagged")
        m["exp_txt"] = m["exposure"].map(lambda x: f"{x:.2f}")
        m["line"] = [[0, 0, 0] if dt else [255, 255, 255] for dt in m["downtown"]]
        m = m[["community_name", "latitude", "longitude", "color", "status", "exp_txt", "line"]]
        layers = [pdk.Layer("ScatterplotLayer", m, get_position="[longitude, latitude]", get_fill_color="color",
                            get_line_color="line", stroked=True, line_width_min_pixels=2, get_radius=700,
                            radius_min_pixels=7, radius_max_pixels=24, pickable=True)]
        ui.deck(layers, tooltip={"html": "<b>{community_name}</b><br/>{status}<br/>Exposure: {exp_txt}",
                                 "style": {"fontSize": "15px"}})
        ui.legend([("Flagged", ui.RED), ("Not flagged (darker = more exposed)", ui.BLUE)])
        st.caption(f"Black outline = downtown baseline set. Exposure source: {how}.")
    with right:
        st.markdown("**Supervisor summary**")
        st.markdown(summary(d, p_day, p_cut, e_cut, df, n_flag, n_dt, n_city, flips))
        if flips[0]:
            with st.expander(f"Which {flips[0]} flipped"):
                st.write(", ".join(x.title() for x in flips[1]))
    with st.expander("All communities"):
        st.dataframe(df.sort_values("exposure", ascending=False)[
            [c for c in ["community_name", "sector", "exposure", "flag", "downtown", "hail_track"] if c in df.columns]],
            hide_index=True, width="stretch",
            column_config={"exposure": st.column_config.ProgressColumn(format="%.2f", min_value=0.0, max_value=1.0)})
