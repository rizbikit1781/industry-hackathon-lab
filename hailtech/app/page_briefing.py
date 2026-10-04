"""Page A: Morning briefing (day-ahead, 06 MDT issue)."""
from __future__ import annotations

import numpy as np
import pandas as pd
import pydeck as pdk
import streamlit as st

import data
import ui

DATE_NOTES = {
    "2024-08-05": "blind case, CAD 3.3B storm",
    "2020-06-13": "CAD 1.3B storm",
}
HIT_MM = 30


def date_label(d: str) -> str:
    note = DATE_NOTES.get(d)
    try:
        nice = pd.Timestamp(d).strftime("%a %d %b %Y")
    except Exception:
        nice = d
    return f"{nice} ({note})" if note else nice


def pick_date(key: str) -> str | None:
    dates = data.score_dates()
    if not dates:
        return None
    cur = st.session_state.get("hd_date")
    idx = dates.index(cur) if cur in dates else (dates.index("2024-08-05") if "2024-08-05" in dates else 0)
    d = st.selectbox("Forecast date (06:00 MDT issue)", dates, index=idx, format_func=date_label, key=f"{key}_date")
    st.session_state["hd_date"] = d
    return d


def assets_frame(sc: dict) -> pd.DataFrame | None:
    rows = sc.get("assets") or []
    if not rows:
        return None
    df = pd.DataFrame(rows)
    need = ["asset_id", "name", "category", "latitude", "longitude", "p_asset"]
    if not set(need) <= set(df.columns):
        return None
    for c, default in [("p_hit_given_day", np.nan), ("value_at_risk", np.nan), ("protect_cost", np.nan),
                       ("observed_mesh_mm", np.nan), ("expected_loss", np.nan), ("protect", None)]:
        if c not in df.columns:
            df[c] = default
    df["p_asset"] = pd.to_numeric(df["p_asset"], errors="coerce").fillna(0.0)
    for c in ("value_at_risk", "protect_cost", "observed_mesh_mm", "p_hit_given_day", "latitude", "longitude"):
        df[c] = pd.to_numeric(df[c], errors="coerce")
    # fill L/C from assets.csv if the score file lacks them
    if df["value_at_risk"].isna().any() or df["protect_cost"].isna().any():
        a = data.assets_csv()
        if a is not None and {"asset_id", "value_at_risk", "protect_cost"} <= set(a.columns):
            m = a.set_index("asset_id")
            df["value_at_risk"] = df["value_at_risk"].fillna(df["asset_id"].map(m["value_at_risk"]))
            df["protect_cost"] = df["protect_cost"].fillna(df["asset_id"].map(m["protect_cost"]))
    df["value_at_risk"] = df["value_at_risk"].fillna(0.0)
    df["protect_cost"] = df["protect_cost"].fillna(np.inf)
    default_protect = df["p_asset"] * df["value_at_risk"] >= df["protect_cost"]
    df["protect_default"] = df["protect"].where(df["protect"].notna(), default_protect).astype(bool)
    return df.dropna(subset=["latitude", "longitude"])


def lc_editor(df: pd.DataFrame, date: str) -> pd.DataFrame:
    g = (df.groupby("category", sort=True)
           .agg(sites=("asset_id", "size"), L=("value_at_risk", "median"), C=("protect_cost", "median"))
           .reset_index())
    g["C"] = g["C"].replace(np.inf, 0.0)
    st.markdown("**What-if: value at risk (L) and cost to protect (C) per category**")
    st.caption("Edit a cell. Protect rule: P x L >= C. Pure arithmetic on the precomputed P; no model runs.")
    ed = st.data_editor(
        g, key=f"lc_editor_{date}", hide_index=True, width="stretch", disabled=["category", "sites"],
        column_config={
            "category": st.column_config.TextColumn("Category"),
            "sites": st.column_config.NumberColumn("Sites"),
            "L": st.column_config.NumberColumn("L: value at risk ($)", min_value=0, step=100_000, format="%d"),
            "C": st.column_config.NumberColumn("C: cost to protect ($)", min_value=0, step=100, format="%d"),
        })
    return ed


def apply_lc(df: pd.DataFrame, ed: pd.DataFrame) -> pd.DataFrame:
    out = df.copy()
    try:
        m = ed.set_index("category")
        L = out["category"].map(pd.to_numeric(m["L"], errors="coerce"))
        C = out["category"].map(pd.to_numeric(m["C"], errors="coerce"))
        out["L"] = L.fillna(out["value_at_risk"])
        out["C"] = C.fillna(out["protect_cost"])
    except Exception:
        out["L"], out["C"] = out["value_at_risk"], out["protect_cost"]
    out["exp_loss"] = out["p_asset"] * out["L"]
    out["protect_now"] = out["exp_loss"] >= out["C"]
    return out


def asset_map(df: pd.DataFrame, state_day: str):
    d = df.copy()
    prep = state_day == "PREPARE"
    d["color"] = [ui.RED if p else (ui.AMBER if prep else ui.BLUE) for p in d["protect_now"]]
    d["decision"] = np.where(d["protect_now"], "PROTECT", ui.plain(state_day or "MONITOR"))
    d["p_txt"] = d["p_asset"].map(lambda x: ui.pct(x, 2))
    d["L_txt"] = d["L"].map(ui.money)
    d["C_txt"] = d["C"].map(ui.money)
    d["el_txt"] = d["exp_loss"].map(ui.money)
    d["mesh_txt"] = d["observed_mesh_mm"].map(lambda x: "n/a" if pd.isna(x) else f"{x:.0f} mm")
    d["radius"] = 350 + 1400 * np.sqrt(d["exp_loss"] / max(float(d["exp_loss"].max()), 1.0))
    d = d[["name", "category", "latitude", "longitude", "color", "decision", "p_txt", "L_txt", "C_txt",
           "el_txt", "mesh_txt", "radius"]]
    layers = [
        pdk.Layer("ScatterplotLayer", d, get_position="[longitude, latitude]", get_fill_color="color",
                  get_radius="radius", radius_min_pixels=7, radius_max_pixels=40, pickable=True, opacity=0.85,
                  stroked=True, get_line_color=[255, 255, 255], line_width_min_pixels=2),
    ]
    tip = {"html": "<b>{name}</b><br/>{category}<br/><b>{decision}</b><br/>P(hit today): {p_txt}<br/>"
                   "L: {L_txt} &nbsp; C: {C_txt}<br/>Expected loss: {el_txt}<br/>Observed MESH: {mesh_txt}",
           "style": {"fontSize": "15px"}}
    ui.deck(layers, tooltip=tip)
    ui.legend([("PROTECT (P x L >= C)", ui.RED), (f"{ui.plain(state_day or 'MONITOR')} (no action yet)",
                                                  ui.AMBER if prep else ui.BLUE)])
    st.caption("Circle size = expected loss. Observed MESH is hindsight (radar, after the day), never a model input.")


def briefing_text(sc: dict, df: pd.DataFrame) -> str:
    d = sc.get("date", "")
    p = sc.get("p_day")
    lines = [f"**HailTech briefing for {date_label(d)}, issued 06:00 MDT.**"]
    lines.append(f"Probability of a regional severe-hail day: **{ui.pct(p)}** "
                 f"(climatology {ui.pct(sc.get('p_day_climatology'))}, single-index rule "
                 f"{ui.pct(sc.get('p_day_single_index'))}). Day state: **{ui.plain(sc.get('state_day', 'MONITOR'))}**.")
    feats = [f for f in (sc.get("top_features") or []) if isinstance(f, dict)][:3]
    if feats:
        lines.append("Main drivers: " + "; ".join(f"{f.get('name')} {f.get('value')}"
                                                 + (f" ({f.get('note')})" if f.get("note") else "") for f in feats) + ".")
    prot = df[df["protect_now"]].sort_values("exp_loss", ascending=False)
    n = len(prot)
    if n:
        top = ", ".join(prot["name"].head(3).map(lambda s: s.split(" (")[0]))
        lines.append(f"Protect **{n} of {len(df)}** sites today, led by {top}. Protection cost "
                     f"{ui.money(prot['C'].sum())} against {ui.money(prot['exp_loss'].sum())} expected loss avoided.")
    else:
        lines.append(f"No site clears the cost-loss bar today (0 of {len(df)}); all stay on "
                     f"{ui.plain(sc.get('state_day', 'MONITOR'))}.")
    ready = [a for a in (sc.get("assets") or []) if isinstance(a, dict) and a.get("ready")]
    if ready:
        lines.append(f"Readiness: put **{len(ready)} of {len(df)}** sites on standby this afternoon (crew on call, "
                     f"customers warned, covered space cleared). Readiness happens before storms form.")
    lines.append("If storms form, the radar nowcast arms and triggers individual sites 0 to 45 minutes ahead.")
    obs = df["observed_mesh_mm"].dropna()
    if len(obs):
        n_hit = int((obs >= HIT_MM).sum())
        caught = int(((df["observed_mesh_mm"] >= HIT_MM) & df["protect_now"]).sum())
        lines.append(f"_Hindsight (radar MESH, not available at 06:00): {n_hit} sites saw hail >= {HIT_MM} mm; "
                     f"{caught} of them were on the protect list._")
    return "  \n".join(lines)


SAFETY = ("**Official warnings come first.** Environment and Climate Change Canada watches and warnings "
          "(weather.gc.ca, Alberta Emergency Alert) always take precedence; a low HailTech score never downgrades "
          "them.  \n**Safety.** No outdoor protection work once thunder is heard or a warning is in effect: "
          "shelter, and wait 30 minutes after the last thunder before going outside (ECCC lightning safety "
          "guidance). Protection actions must be finished before the storm arrives or skipped.")


def render():
    st.title("Morning briefing")
    st.caption("Day-ahead layer. P(asset hit today) = P(regional hail day | 06 MDT atmosphere) x P(hit | hail day). "
               "Protect if P x L >= C.")
    d = pick_date("brief")
    if d is None:
        ui.not_computed("Morning scores", "data/processed/scores/<YYYY-MM-DD>.json",
                        "Run the scoring script for the demo dates (5 Aug 2024, 13 Jun 2020, a quiet day).")
        return
    sc = data.scores(d)
    if sc is None:
        ui.not_computed(f"Score for {d}", f"data/processed/scores/{d}.json (missing or unreadable)")
        return
    ui.fixture_banner(f"scores/{d}.json")

    state = str(sc.get("state_day") or "MONITOR").upper()
    c1, c2, c3, c4 = st.columns([1.4, 1, 1, 1.2])
    with c1:
        st.markdown("**P(regional hail day)**")
        st.markdown(f'<p class="hd-big">{ui.pct(sc.get("p_day"))}</p>', unsafe_allow_html=True)
        st.markdown(f'<div class="hd-sub">source: {sc.get("source", "?")}</div>', unsafe_allow_html=True)
    c2.metric("Climatology", ui.pct(sc.get("p_day_climatology")))
    c3.metric("Single-index rule", ui.pct(sc.get("p_day_single_index")))
    with c4:
        st.markdown("**Day state**")
        st.markdown(ui.badge(ui.plain(state), ui.STATE_RGB.get(state, ui.GREY)), unsafe_allow_html=True)

    df = assets_frame(sc)
    if df is None:
        ui.not_computed("Per-asset scores", f"scores/{d}.json -> assets")
        return

    left, right = st.columns([1.6, 1])
    with right:
        feats = [f for f in (sc.get("top_features") or []) if isinstance(f, dict)]
        if feats:
            st.markdown("**Top features (06 MDT atmosphere)**")
            st.dataframe(pd.DataFrame(feats).reindex(columns=["name", "value", "note"]), hide_index=True,
                         width="stretch")
        ed = lc_editor(df, d)
    df = apply_lc(df, ed)
    flips = int((df["protect_now"] != df["protect_default"]).sum())
    with right:
        k1, k2 = st.columns(2)
        k1.metric("Sites to protect", f"{int(df['protect_now'].sum())} / {len(df)}")
        k2.metric("Flipped vs defaults", flips)
    with left:
        asset_map(df, state)

    st.subheader("Supervisor briefing")
    st.markdown(briefing_text(sc, df))
    st.warning(SAFETY)

    st.subheader("Sites by expected loss")
    t = df.sort_values("exp_loss", ascending=False)
    t = pd.DataFrame({
        "Decision": np.where(t["protect_now"], "PROTECT", state), "Site": t["name"], "Category": t["category"],
        "P(hit | hail day)": t["p_hit_given_day"], "P(hit today)": t["p_asset"], "L ($)": t["L"], "C ($)": t["C"],
        "Expected loss ($)": t["exp_loss"], "Observed MESH (mm)": t["observed_mesh_mm"],
        "Changed by edit": np.where(t["protect_now"] != t["protect_default"], "yes", ""),
    })
    st.dataframe(t, hide_index=True, width="stretch", column_config={
        "P(hit | hail day)": st.column_config.NumberColumn(format="%.3f"),
        "P(hit today)": st.column_config.NumberColumn(format="%.4f"),
        "L ($)": st.column_config.NumberColumn(format="$%d"),
        "C ($)": st.column_config.NumberColumn(format="$%d"),
        "Expected loss ($)": st.column_config.NumberColumn(format="$%.0f"),
        "Observed MESH (mm)": st.column_config.NumberColumn(format="%.0f"),
    })
