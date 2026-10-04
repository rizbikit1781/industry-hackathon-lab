"""HailTech dashboard. Reads precomputed files only; never runs a model.

Run:  cd hailday && .venv/bin/streamlit run app/streamlit_app.py
Dev:  HAILDAY_FIXTURES=1 to fall back to synthetic fixtures in app/fixtures/ when a real file is missing.
"""
import os
import sys
import traceback
from pathlib import Path

APP_DIR = Path(__file__).resolve().parent
if str(APP_DIR) not in sys.path:
    sys.path.insert(0, str(APP_DIR))

import streamlit as st  # noqa: E402

st.set_page_config(page_title="HailTech", page_icon=":cloud_with_rain:", layout="wide",
                   initial_sidebar_state="expanded")

import data  # noqa: E402
import page_backtest  # noqa: E402
import page_briefing  # noqa: E402
import page_flags  # noqa: E402
import page_how  # noqa: E402
import page_replay  # noqa: E402
import page_story  # noqa: E402
import ui  # noqa: E402

PAGES = {
    page_story.TITLE: page_story.render,          # default: the plain-words story
    # --- "Details for judges" (heading drawn by ui.CSS above the 2nd option) ---
    "Morning briefing": page_briefing.render,
    "Storm replay": page_replay.render,
    "Backtest": page_backtest.render,
    "Community flags": page_flags.render,
    "How it works": page_how.render,
}

ui.style()
with st.sidebar:
    st.markdown("# HailTech")
    st.markdown("Hail protection for Calgary outdoor assets: **a number by breakfast, a trigger before the storm.**")
    page = st.radio("Page", list(PAGES), key="nav", label_visibility="collapsed")
    st.divider()
    if data.fixtures_enabled():
        st.warning("Fixture fallback ON (HAILDAY_FIXTURES=1). Panels using synthetic data are labelled.")
    st.caption("All panels read precomputed files from data/processed/. No model inference runs in this app.")

try:
    PAGES[page]()
except Exception as e:  # never show a traceback on stage
    if os.environ.get("HAILDAY_DEBUG"):
        raise
    st.error(f"This panel could not be drawn from the current files ({type(e).__name__}). "
             "The other pages still work.")
    with st.expander("Details for the team"):
        st.code(traceback.format_exc())
