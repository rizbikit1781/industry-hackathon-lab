"""Page E: How it works (architecture and data sources)."""
from __future__ import annotations

import pandas as pd
import streamlit as st

DOT = r"""
digraph G {
  rankdir=LR; bgcolor="transparent"; nodesep=0.35; ranksep=0.5;
  node [shape=box, style="rounded,filled", fontname="Helvetica", fontsize=13, fillcolor="#ffffff", color="#444444", penwidth=1.4];
  edge [color="#555555", penwidth=1.4, fontname="Helvetica", fontsize=11];

  subgraph cluster_src { label="Public data"; fontname="Helvetica-Bold"; fontsize=14; color="#bbbbbb"; style="rounded";
    ichd  [label="ECCC hail reports\n(ICHD, 2006-2022)"];
    era5  [label="ERA5 reanalysis\n06 MDT atmosphere"];
    om    [label="Open-Meteo\nforecast (today)"];
    mesh  [label="NOAA MRMS MESH\n1 km radar hail size"];
    mrms5 [label="MRMS radar\n2-min volumes"];
    nhp   [label="Calgary communities\n+ 23 asset sites"];
  }

  subgraph cluster_day { label="Day-ahead layer (06 MDT)"; fontname="Helvetica-Bold"; fontsize=14; color="#1e64c8"; style="rounded";
    s1 [label="Stage 1: regional hail-day model\ngradient boosting + calibration\nP(day)", fillcolor="#e3edfa"];
    s2 [label="Stage 2: per-cell hit rate\nP(hit | hail day)", fillcolor="#e3edfa"];
    x  [label="P(asset) = P(day) x P(hit | day)", shape=ellipse, fillcolor="#e3edfa"];
    d  [label="Protect if P x L >= C\nMONITOR / PREPARE", shape=diamond, fillcolor="#fde9e9"];
  }

  subgraph cluster_now { label="Nowcast layer (0-45 min)"; fontname="Helvetica-Bold"; fontsize=14; color="#eb8c00"; style="rounded";
    trk [label="Storm tracking\n+ extrapolation", fillcolor="#fff1dc"];
    arm [label="Per-site P(>=30 mm)\nARM / TRIGGER", shape=diamond, fillcolor="#fde9e9"];
  }

  files [label="Precomputed files\nscores/, nowcast/, backtest\n(the app only reads these)", shape=folder, fillcolor="#f2f2f2"];
  app   [label="Dashboard\nbriefing, replay, backtest,\ncommunity flags", fillcolor="#e9f6ef"];
  user  [label="Site operator / insurer /\ncity supervisor", shape=oval, fillcolor="#ffffff"];

  ichd -> s1 [label="labels"]; era5 -> s1 [label="features"]; om -> s1 [style=dashed, label="today"];
  mesh -> s2; s1 -> x; s2 -> x; nhp -> d; x -> d;
  mrms5 -> trk; trk -> arm; nhp -> arm;
  d -> files; arm -> files; files -> app; app -> user;
}
"""

SOURCES = [
    ("Integrated Canadian Hail Database (ECCC reports)", "Day labels, 2006-2022",
     "Zenodo record 8015925", "Creative Commons (per Zenodo record)"),
    ("ERA5 reanalysis", "06 MDT atmosphere features (CAPE, shear, freezing level ...)",
     "Copernicus Climate Data Store", "Copernicus licence (free, attribution)"),
    ("Open-Meteo", "Fallback and same-day forecast features", "open-meteo.com", "CC BY 4.0"),
    ("NOAA MRMS MESH and radar", "Per-site hail climatology, nowcast, verification", "NOAA / AWS Open Data",
     "Public domain (US Government work)"),
    ("Northern Hail Project (NHP) 5 Aug 2024 damage contours", "Validation of the blind case only",
     "Northern Hail Project", "CC BY-NC 4.0 (non-commercial validation)"),
    ("City of Calgary Open Data", "Business licence points for asset sites; community centroids (Case 4)",
     "data.calgary.ca", "Open Government Licence - City of Calgary"),
    ("OpenStreetMap", "Some asset site footprints", "openstreetmap.org", "ODbL"),
]


def render():
    st.title("How it works")
    st.markdown(
        "**Two layers, one decision per site.** At 06:00 MDT HailTech estimates the chance of a regional "
        "severe-hail day from the morning atmosphere, multiplies it by each site's historical radar hit rate, "
        "and recommends protection wherever the expected loss exceeds the cost of acting. If storms form, the "
        "radar nowcast arms and triggers individual sites 0 to 45 minutes ahead.")
    try:
        st.graphviz_chart(DOT, width="stretch")
    except Exception:
        st.code(DOT, language="dot")
    st.subheader("Design rules")
    st.markdown(
        "- **Out-of-sample only**: leave-one-year-out, always compared with climatology and a single-index rule.\n"
        "- **Explainable inputs**: every feature is a named meteorological quantity.\n"
        "- **Demo-safe**: the app reads precomputed files; no model runs here and no network calls are needed.\n"
        "- **Decision, not display**: each site gets PROTECT / MONITOR with a dollar consequence.")
    st.subheader("Data sources and licences")
    st.dataframe(pd.DataFrame(SOURCES, columns=["Dataset", "Used for", "Where", "Licence"]), hide_index=True,
                 width="stretch")
