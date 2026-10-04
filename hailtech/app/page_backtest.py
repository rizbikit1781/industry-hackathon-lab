"""Page C: Backtest (leave-one-year-out skill, reliability, dollar value)."""
from __future__ import annotations

import altair as alt
import numpy as np
import pandas as pd
import streamlit as st

import data
import ui

MODELS = {"climatology": "Climatology", "single_index": "Single-index rule", "hailday": "HailTech"}
POLICIES = {"never": "Never protect", "always": "Always protect", "climatology": "Climatology",
            "single_index": "Single-index rule", "hailday": "HailTech", "oracle_day": "Perfect day forecast"}
COLORS = {"Climatology": "#888888", "Single-index rule": "#eb8c00", "HailTech": "#1e64c8"}


def _src_picker():
    srcs = sorted(set(data.available_sources("backtest", "json")) | set(data.available_sources("dollar_backtest", "json"))
                  | set(data.available_sources("oof", "parquet")), key=lambda s: data.SOURCES.index(s))
    if not srcs:
        return None
    if len(srcs) == 1:
        st.caption(f"Feature source: **{srcs[0]}**")
        return srcs[0]
    return st.radio("Feature source", srcs, horizontal=True, key="bt_src")


def skill_table(bt: dict):
    rows = []
    for k, lab in MODELS.items():
        m = bt.get(k)
        if not isinstance(m, dict):
            continue
        rows.append({"Model": lab, "AUC": m.get("auc"), "Brier": m.get("brier"), "POD": m.get("pod"),
                     "FAR": m.get("far"), "CSI": m.get("csi"), "Hits": m.get("hits"), "Misses": m.get("misses"),
                     "False alarms": m.get("false_alarms"), "Cutoff": m.get("cutoff")})
    if not rows:
        st.info("Backtest file has no model blocks.")
        return
    f3 = st.column_config.NumberColumn(format="%.3f")
    st.dataframe(pd.DataFrame(rows), hide_index=True, width="stretch",
                 column_config={c: f3 for c in ["AUC", "Brier", "POD", "FAR", "CSI", "Cutoff"]})
    meta = bt.get("_meta") or {}
    base = next((bt[k].get("base_rate") for k in MODELS if isinstance(bt.get(k), dict)), None)
    bits = []
    if meta.get("years"):
        y = meta["years"]
        bits.append(f"years {y[0]}-{y[-1]}" if isinstance(y, list) and y else f"years {y}")
    if meta.get("n_days"):
        bits.append(f"{meta['n_days']:,} days")
    if meta.get("n_severe"):
        bits.append(f"{meta['n_severe']} severe-hail days")
    if base is not None:
        bits.append(f"base rate {ui.pct(base, 1)}")
    st.caption("Leave-one-year-out, out-of-sample. " + ", ".join(bits) + ". AUC: ranking skill (0.5 = coin flip). "
               "Brier: lower is better. CSI = hits / (hits + misses + false alarms) at the cutoff.")
    if meta.get("features"):
        st.caption("Features: " + ", ".join(map(str, meta["features"])))


def reliability_chart(bt: dict):
    rows = []
    for k, lab in MODELS.items():
        for r in ((bt.get(k) or {}).get("reliability") or []):
            if isinstance(r, dict) and r.get("forecast") is not None and r.get("observed") is not None:
                rows.append({"Model": lab, "forecast": float(r["forecast"]), "observed": float(r["observed"]),
                             "n": int(r.get("n") or 0)})
    if not rows:
        st.info("Reliability bins not in backtest file.")
        return
    df = pd.DataFrame(rows)
    mx = float(max(df["forecast"].max(), df["observed"].max(), 0.1))
    mx = min(1.0, np.ceil(mx * 10) / 10)
    diag = alt.Chart(pd.DataFrame({"x": [0, mx], "y": [0, mx]})).mark_line(strokeDash=[6, 4], color="#444").encode(
        x="x:Q", y="y:Q")
    dom = [m for m in COLORS if m in set(df["Model"])]
    base = alt.Chart(df).encode(
        x=alt.X("forecast:Q", title="Forecast probability", scale=alt.Scale(domain=[0, mx]), axis=alt.Axis(format="%")),
        y=alt.Y("observed:Q", title="Observed frequency", scale=alt.Scale(domain=[0, mx]), axis=alt.Axis(format="%")),
        color=alt.Color("Model:N", scale=alt.Scale(domain=dom, range=[COLORS[m] for m in dom]),
                        legend=alt.Legend(orient="top")),
        tooltip=["Model", alt.Tooltip("forecast:Q", format=".1%"), alt.Tooltip("observed:Q", format=".1%"), "n"])
    ch = diag + base.mark_line(strokeWidth=3) + base.mark_circle().encode(size=alt.Size("n:Q", legend=None,
                                                                                         scale=alt.Scale(range=[30, 400])))
    st.altair_chart(ch.properties(height=380), width="stretch")
    st.caption("On the dashed line, a forecast of 30% verifies 30% of the time. Dot size = days in the bin.")


def oof_by_year(df: pd.DataFrame):
    cols = [c for c in ["p_climatology", "p_single_index", "p_hailday"] if c in df.columns]
    if "year" not in df.columns or "severe" not in df.columns or not cols:
        return
    g = df.groupby("year").agg(days=("severe", "size"), severe=("severe", "sum"),
                               **{MODELS[c[2:]]: (c, "sum") for c in cols})
    st.markdown("**Expected vs observed severe days per year (sum of daily probabilities)**")
    long = g.reset_index().melt(id_vars=["year", "days"], var_name="Series", value_name="Days")
    long["Series"] = long["Series"].replace({"severe": "Observed"})
    dom = ["Observed"] + [MODELS[c[2:]] for c in cols]
    rng = ["#c81e2d"] + [COLORS[MODELS[c[2:]]] for c in cols]
    ch = alt.Chart(long).mark_line(point=True, strokeWidth=2.5).encode(
        x=alt.X("year:O", title=None), y=alt.Y("Days:Q", title="Severe-hail days"),
        color=alt.Color("Series:N", scale=alt.Scale(domain=dom, range=rng), legend=alt.Legend(orient="top")),
        tooltip=["year", "Series", alt.Tooltip("Days:Q", format=".1f")])
    st.altair_chart(ch.properties(height=280), width="stretch")


def dollar_section(db: dict):
    rows = pd.DataFrame([r for r in db.get("rows") or [] if isinstance(r, dict)])
    if rows.empty or "policy" not in rows:
        st.info("Dollar backtest has no rows.")
        return
    attrs = db.get("attrs") or {}
    rows["Policy"] = rows["policy"].map(lambda p: POLICIES.get(p, p))
    order = [p for p in POLICIES if p in set(rows["policy"])] + [p for p in rows["policy"] if p not in POLICIES]
    rows = rows.set_index("policy").loc[order].reset_index()
    for c in ["total_cost", "protections", "hits", "hits_protected", "value_vs_never", "share_of_perfect_value"]:
        rows[c] = pd.to_numeric(rows[c], errors="coerce") if c in rows else np.nan
    hd = rows[rows["policy"] == "hailday"]
    if not hd.empty:
        a, b, c = st.columns(3)
        a.metric("HailTech value vs never protecting", ui.money(hd["value_vs_never"].iloc[0]))
        b.metric("Share of perfect-forecast value", ui.pct(hd["share_of_perfect_value"].iloc[0]))
        if pd.notna(hd["hits"].iloc[0]) and pd.notna(hd["hits_protected"].iloc[0]) and hd["hits"].iloc[0]:
            c.metric("Hits protected", f"{int(hd['hits_protected'].iloc[0]):,} / {int(hd['hits'].iloc[0]):,}")
    t = rows[["Policy", "total_cost", "value_vs_never", "share_of_perfect_value", "protections", "hits_protected",
              "hits"]].rename(columns={"total_cost": "Total cost", "value_vs_never": "Saved vs never",
                                       "share_of_perfect_value": "Share of perfect value",
                                       "protections": "Protections", "hits_protected": "Hits protected",
                                       "hits": "Hits"})
    st.dataframe(t, hide_index=True, width="stretch", column_config={
        "Total cost": st.column_config.NumberColumn(format="$%.0f"),
        "Saved vs never": st.column_config.NumberColumn(format="$%.0f"),
        "Share of perfect value": st.column_config.ProgressColumn(format="%.2f", min_value=0.0, max_value=1.0),
    })
    bars = rows.dropna(subset=["share_of_perfect_value"])
    bars = bars[bars["policy"] != "never"]
    if not bars.empty:
        bars = bars.assign(hl=np.where(bars["policy"] == "hailday", "HailTech", "other"))
        ch = alt.Chart(bars).mark_bar().encode(
            y=alt.Y("Policy:N", sort=list(bars["Policy"]), title=None, axis=alt.Axis(labelFontSize=14)),
            x=alt.X("share_of_perfect_value:Q", title="Share of the value a perfect forecast would capture",
                    axis=alt.Axis(format="%")),
            color=alt.Color("hl:N", scale=alt.Scale(domain=["HailTech", "other"], range=["#1e64c8", "#9aa5b1"]),
                            legend=None),
            tooltip=["Policy", alt.Tooltip("share_of_perfect_value:Q", format=".1%")])
        st.altair_chart(ch.properties(height=40 * len(bars) + 40), width="stretch")
    bits = []
    if attrs.get("n_days"):
        bits.append(f"{attrs['n_days']} days")
    if attrs.get("n_cells"):
        bits.append(f"{attrs['n_cells']:,} grid cells treated as generic assets")
    if attrs.get("value_at_risk") is not None:
        bits.append(f"L = {ui.money(attrs['value_at_risk'])}")
    if attrs.get("protect_cost") is not None:
        bits.append(f"C = {ui.money(attrs['protect_cost'])}")
    if attrs.get("size_mm"):
        bits.append(f"hit = MESH >= {attrs['size_mm']} mm")
    st.caption("Dollar backtest: " + ", ".join(bits) + ". Negative share means worse than never protecting.")


def value_section(vc: dict):
    alphas = vc["alphas"]
    rows = [{"C/L": a, "Policy": POLICIES.get(name, name), "Value": v}
            for name, vals in vc["curves"].items() for a, v in zip(alphas, vals)
            if v is not None and np.isfinite(v)]
    df = pd.DataFrame(rows)
    if df.empty:
        st.info("Value curve has no finite points.")
        return
    df["Value"] = df["Value"].clip(lower=-0.5)
    line = alt.Chart(df).mark_line(strokeWidth=2.5).encode(
        x=alt.X("C/L:Q", scale=alt.Scale(type="log"), title="Cost / avoidable-loss ratio (log)"),
        y=alt.Y("Value:Q", title="Relative economic value", scale=alt.Scale(domain=[-0.5, 1])),
        color=alt.Color("Policy:N", legend=alt.Legend(orient="top")),
        tooltip=["Policy", alt.Tooltip("C/L:Q", format=".1e"), alt.Tooltip("Value:Q", format=".2f")])
    zero = alt.Chart(pd.DataFrame({"y": [0]})).mark_rule(strokeDash=[4, 4], color="#666").encode(y="y:Q")
    marks = pd.DataFrame([{"Category": c, "C/L": m["readiness_alpha"]}
                          for c, m in (vc.get("category_alphas") or {}).items()
                          if m.get("readiness_alpha") and m["readiness_alpha"] > 0])
    layers = [line, zero]
    if not marks.empty:
        layers.append(alt.Chart(marks).mark_rule(color="#c81e2d", opacity=0.35).encode(
            x="C/L:Q", tooltip=["Category", alt.Tooltip("C/L:Q", format=".1e")]))
    st.altair_chart(alt.layer(*layers).properties(height=340), width="stretch")
    st.caption("1 = perfect forecast, 0 = no better than the best of always-ready / never-ready, below 0 = worse. "
               "Each asset is a 1 km MESH cell in the label box, 2020-2025, hit = MESH >= 30 mm. "
               "Red rules: where each asset category's readiness cost sits (assumed costs). "
               "No single dollar figure is claimed: the value depends on the user's own cost ratio.")


def render():
    st.title("Backtest")
    st.caption("Is HailTech better than what a site already has? Every number here is out-of-sample.")
    src = _src_picker()
    if src is None:
        ui.not_computed("Backtest", "data/processed/backtest_<era5|openmeteo>.json",
                        "Run the training script (leave-one-year-out) first.")
        caveats()
        return
    bt = data.backtest(src)
    ui.fixture_banner(f"backtest_{src}.json", f"oof_{src}.parquet", f"dollar_backtest_{src}.json")
    st.subheader("Three forecasts, same days")
    if bt is None:
        ui.not_computed("Skill table", f"backtest_{src}.json")
    else:
        skill_table(bt)
        c1, c2 = st.columns(2)
        with c1:
            st.markdown("**Reliability**")
            reliability_chart(bt)
        with c2:
            o = data.oof(src)
            if o is not None:
                oof_by_year(o)
            else:
                st.info(f"Per-year view not yet computed (oof_{src}.parquet).")

    st.subheader("Economic value across cost ratios")
    vc = data.value_curve(src)
    if vc is None:
        ui.not_computed("Value curve", f"value_curve_{src}.json")
    else:
        value_section(vc)
    db = data.dollar_backtest(src)
    with st.expander("Dollar backtest at the assumed readiness costs"):
        if db is None:
            ui.not_computed("Dollar backtest", f"dollar_backtest_{src}.json")
        else:
            dollar_section(db)
    caveats()


def caveats():
    st.subheader("Honest caveats")
    st.markdown(
        "- **Labels** are ECCC severe-hail reports (via the Integrated Canadian Hail Database), 2006 to 2022. "
        "Reports follow people: hail on empty farmland goes unreported, so the label set has a population bias "
        "toward Calgary and the highway corridors.\n"
        "- **MESH runs hot.** Radar-estimated hail size overstates ground hail size, so per-site hit rates "
        "(MESH >= 30 mm) are an upper-leaning estimate. 2023 Jun-Nov is excluded (Canadian radar feed outage in MRMS).\n"
        "- **Dollar values are assumptions.** L and C per category are illustrative defaults, not site data; "
        "the morning briefing lets you change them.\n"
        "- The 5 Aug 2024 case is blind: outside the label years and never used in training.")
