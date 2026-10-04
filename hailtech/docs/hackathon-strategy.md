# IEEE YP Industry Hackathon 2026: Strategy (v3, Calgary Hail Predictor)

**Event:** Fri Oct 2 to Sun Oct 4, 2026, Hunter Hub, University of Calgary
**Written:** Sat Oct 3, mid-afternoon. About 21 hours to the submission deadline.
**Goal:** 1st overall. Make the stage finals for Fan Favourite. ElevenLabs prize is a stretch, not the core.
**Constraint:** No oil & gas work (conflict of interest). This project has none.

---

## TL;DR

**Case:** Software & Computational Math, Case 4 (Neighbourhood Smoke-and-Hail Flag), Option B, with the smoke leg dropped. Tell the organizers tonight: *"Software stream, Option B, Case 4, hail focus, extended with ECCC's hail report database and ERA5 reanalysis."* Staying inside Case 4 means nothing needs validating.

**Pitch:** **"HailTech"**: every morning, one calibrated probability that severe hail (20 mm or larger) hits Calgary that day, computed from the 6 AM atmosphere, trained on 18 years of real ECCC hail reports. Then the community flag list Case 4 asks for, with the cutoff a supervisor can move.

**Why it's a hackathon winner, not a chatbot:** the deliverable is a classifier with a backtest. Baseline is climatology and a CAPE-only rule. The improvement loop is visible: model beats baseline, then the noon update re-scores the day, then the cutoff moves and the judge sees which communities flip.

**Numbers that hold up in Q&A (all verified today):**
- 5 Aug 2024 Calgary hailstorm: CAD 3.29 B insured, ~130,000 claims. 13 Jun 2020: CAD 1.3 B.
- ECCC Integrated Canadian Hail Database 2005–2022: 7,000 reports, 2,816 in Alberta, **170 severe-hail days in the Calgary box, about 9.4 per year**, 91 % of severe reports between 1 PM and 9 PM MDT, July peak.
- 5 Aug 2024 had modest buoyancy (SBCAPE ~950 J/kg) and strong shear (~45 kt). Forecast models "had no indication of a major event" from CAPE alone. That is the model's reason to exist: it learns CAPE times shear, not CAPE.

---

## 0. What changed from v2 and why

v2 was CivicSignal (311 dispatch + voice). The team switched to a hail predictor on Sat Oct 3. Decisions made while switching:

| Question | Answer | Evidence |
|---|---|---|
| Smoke or hail? | Hail only. | Team call. |
| Flagger or predictor? | Predictor, with Case 4's community flag list on top. | Rubric's 30 % criterion wants a decision from data plus an improvement round. A trained model with a backtest scores that better than threshold rules. |
| Option A or B? | B (Case 4). | Keeps the case's community table and flag framing. No organizer validation needed. |
| Labels? | ECCC Integrated Canadian Hail Database 2005–2022 (Zenodo 8015925). | Downloaded and counted. Public, CC licence, lat/lon, UTC hour, diameter in mm. |
| Predictors? | ERA5 reanalysis (Copernicus CDS) for history; Open-Meteo forecast API for the live demo. | Open-Meteo's *archive* returns null for CAPE and pressure levels (tested). Its *forecast* endpoint returns CAPE, CIN, lifted index, freezing level and pressure-level fields (tested). |
| Radar nowcast (MESH, dual-pol, lightning jumps)? | Roadmap only. | ECCC Datamart publishes only rendered CAPPI/DPQPE GIFs, about 30 days retained. No volume scans, no dual-pol fields, no historical archive. Not buildable this weekend. |

Reference documents in this folder:
- `hail-sme-report.md`: the physics, every index with thresholds and the ERA5 variables behind it, published model skill, the exact ERA5 request.
- `Calgary_Hail_Public_Data_Parameters.xlsx`: every public data source, corrected for what is public, with a "Tier 1 - Day-ahead build" feature set.

---

## 1. What the rules reward

| Criterion | Weight | How HailTech scores it |
|---|---|---|
| Autonomous Reasoning + Data-Driven Decisions | **30 %** | Climatology baseline → CAPE-only rule → trained model, same backtest, same metrics. Then two revisions on screen: the noon (18 UTC) re-score, and the cutoff move with the flip count. |
| Real Industrial Problem & Relevance | 20 % | Hailstorm Alley. CAD 3.29 B in one afternoon. Named users: City Emergency Management, Calgary Transit fleet yards, airport ground ops, auto dealers, insurers. Get a mentor quote. |
| Execution & Software Architecture | 20 % | Live: pick a date, the model scores it, the map flags communities. One diagram. Rationale: reanalysis for history, forecast API for today, gradient boosting because 170 positives can't feed a neural net. |
| Commercialization | 15 % | Pilot: one summer with Calgary Transit or the City's fleet (park buses under cover on a red day). Scales to every Hailstorm Alley municipality and to insurers' "move your car" alerts. Roadmap: radar nowcast once ECCC volumetric data is licensed. |
| Presentation & Demo | 15 % | 5 min + 3 min. One wow moment: 5 Aug 2024 scored blind. |

Handbook signals that still apply:
- "Hard science, not productivity apps." Open on the backtest and the physics, never on a UI.
- Confirm track and case with organizers **tonight by 11:59 PM** (email `nagusubra@ieee.org` or Discord DM). Unconfirmed selections forfeit.
- Submit a GitHub Issue on `nagusubra/industry-hackathon-lab` by **Sun 12:00 PM MDT sharp**. Min 2, max 5 screenshots. Video link optional but recommended.
- Every member can still claim ElevenLabs Creator tier (131k credits) via the ElevenLabs Discord `#coupon-codes`.

---

## 2. The problem, stated precisely

> Given the state of the atmosphere over the Calgary region at 6 AM (12 UTC), estimate the probability that hail of 20 mm or more is reported inside the Calgary box that day. Beat climatology and a single-index rule on 18 summers of real reports. Re-score at noon. Turn the probability into a short community flag list whose cutoff a supervisor controls.

**Target.** One label per *local* (MDT) day, May–September, 2005–2022: 1 if any ICHD report with diameter ≥ 20 mm falls inside the box, else 0. About 2,750 days, about 170 positives (6 %). Drop 2005 (one report; clearly incomplete) or keep it and say so.

**Box.** Labels: 50.4–51.7 N, 113.2–114.9 W (Cochrane to Strathmore, Airdrie to High River). Features: a wider box, 49.5–52.5 N, 112.0–115.5 W, so the foothills initiation zone upstream is inside the feature grid. Use box max and mean of each derived index.

**Why 12 UTC.** Severe reports in the box peak 3–7 PM MDT; 91 % fall between 1 PM and 9 PM. 6 AM is a real forecast. 18 UTC (noon) is a legitimate update. 00 UTC is mid-event and is used only as a diagnostic.

**UTC pitfall.** ICHD timestamps are UTC. A report at 00:45–06:00 UTC belongs to the *previous* MDT day. Convert before labelling, or evening storms split across two days.

---

## 3. Data

| Data | Source | Status |
|---|---|---|
| Hail reports 2005–2022 | ECCC Integrated Canadian Hail Database v1.0.0, https://zenodo.org/records/8015925, `integrated_canadian_hail_db.csv` (415 KB) | Downloaded. Columns: `Start Time, Year, Month, Day, Hour, Longitude, Latitude, Province Code, Reference Object, Hail Diameter (mm)`. |
| ERA5 single levels + pressure levels | Copernicus CDS, `reanalysis-era5-single-levels`, `reanalysis-era5-pressure-levels` | **Needs a CDS account and `~/.cdsapirc`. Submit the request first; it queues.** Request spec is in §4. |
| Today's forecast | Open-Meteo forecast API, no key: `https://api.open-meteo.com/v1/forecast?latitude=51.05&longitude=-114.07&hourly=cape,convective_inhibition,lifted_index,freezing_level_height,temperature_850hPa,temperature_500hPa,wind_speed_500hPa,wind_direction_500hPa,...&timezone=America/Edmonton` | Tested, returns values. |
| Surface history (fallback features) | Open-Meteo archive API, `https://archive-api.open-meteo.com/v1/archive` | Tested. T, dewpoint, pressure, wind, BLH, precipitation. **No CAPE, no pressure levels.** |
| Communities | Case 4 `data/neighbourhoods_hail_scenario.csv`: 92 communities, centroids, `hail_track` high/medium/low | In the case folder. `hail_track` is a news-derived scenario label, not claims data; the case README says so. |
| ERA5 sanity set | ECCC ERA5 extracts for 2,092 ICHD events, https://zenodo.org/records/10041843 | Optional. Positives only. Use to check our derivations match theirs. |
| Case studies outside the label years | ERA5 for 13 Jun 2020 (in training), 5 Aug 2024 (blind) | Pull 2023–2025 summers too; cheap, same request. |

**Setup gotcha (Macs):** python.org Python 3.11 fails HTTPS with `CERTIFICATE_VERIFY_FAILED`. Run `/Applications/Python 3.11/Install Certificates.command` once, or fetch with `requests`/`curl`. `pandas` and `openpyxl` are not installed yet in this environment; `pip install -r requirements.txt` in the case folder, then add `cdsapi xarray netCDF4 metpy scikit-learn streamlit pydeck`.

---

## 4. The model

### 4.1 Features (ranked; from `hail-sme-report.md` §6)

1. **WMAXSHEAR** = sqrt(2 × MUCAPE) × 0–6 km bulk shear. The single best discriminator in the literature.
2. ERA5 `cape` (effectively most-unstable CAPE), derived MLCAPE/SBCAPE, `convective_inhibition`.
3. 0–6 km bulk shear (10 m to 500 hPa); 925–500 hPa shear (the AR-HAIL form).
4. SHIP, derived per the SPC formula. Expect it to be mis-calibrated for Alberta; the trees re-threshold it.
5. 700–500 hPa lapse rate; 500 hPa temperature.
6. Wet-bulb-zero height AGL (MetPy wet-bulb profile) and `zero_degree_level` minus terrain.
7. Low-level moisture: 2 m dewpoint, 850 hPa specific humidity, `total_column_water_vapour`.
8. `k_index`, `total_totals_index` (native, free).
9. 700 and 500 hPa dewpoint depression; hail-growth-zone (−10 to −30 °C) depth.
10. 500/700 hPa wind speed and direction (storms moved NW/NE on 13 Jun 2020, SE on 5 Aug 2024; don't hard-code).
11. Day-of-year as sin/cos. **Never the year** (reporting rates changed 8× across years).

Mask ERA5 pressure levels below `surface_pressure` (about 890 hPa at Calgary); 1000–900 hPa are underground.

### 4.2 The one ERA5 request

Submit once, first thing. Both datasets, `product_type: reanalysis`, `format: netcdf`.

- Years 2005–2025 (2023–2025 only for case studies), months 05–09, all days.
- Hours UTC: `00:00, 06:00, 12:00, 18:00`.
- Area N/W/S/E: `52.5, -115.5, 49.5, -112.0`.
- Single-level: `convective_available_potential_energy, convective_inhibition, k_index, total_totals_index, zero_degree_level, total_column_water_vapour, boundary_layer_height, 2m_temperature, 2m_dewpoint_temperature, 10m_u_component_of_wind, 10m_v_component_of_wind, surface_pressure, convective_precipitation, geopotential`.
- Pressure-level: `temperature, u_component_of_wind, v_component_of_wind, geopotential, relative_humidity, specific_humidity` at `1000 975 950 925 900 875 850 825 800 775 750 700 650 600 550 500 450 400 350 300 250 200`.

If the queue is slow, split by year and start the derivation code on the first year that lands.

### 4.3 Baselines and the improvement loop (the 30 % criterion)

Same 18-summer backtest, leave-one-year-out cross-validation (never random splits; days within a year are correlated).

| Policy | What it is |
|---|---|
| **Climatology** | P(hail) = that month's historical rate. The "lazy" answer. |
| **Single-index rule** | Flag if ERA5 CAPE at 12 UTC ≥ cutoff (or SHIP ≥ 1). What a forecaster's rule of thumb looks like. |
| **HailTech model** | `HistGradientBoostingClassifier` (sklearn; no new dependency) on the §4.1 features, isotonic-calibrated. |
| **Revision 1: noon update** | Same model on 18 UTC features. Show which days change category. |
| **Revision 2: cutoff move** | Supervisor sets the operating point (miss cost vs false-alarm cost). Show the flip count and the cost curve. |

Metrics to report for every policy: AUC, Brier score, CSI / POD / FAR at the chosen cutoff, reliability diagram. Realistic target for a single city box with ~9 positives a year: AUC 0.80–0.90, CSI 0.3–0.5. Published upper bounds are a Germany-wide ERA5 CNN at CSI 0.58 and AR-HAIL at AUC > 0.95 on gridded hourly Europe; say why ours is lower if asked.

**Hero moment:** score **5 Aug 2024** blind (it is outside the label years). Show the feature values: modest CAPE, strong shear, and the model's probability versus the CAPE-only rule's.

**Target sentence:** "On 18 summers of real Calgary hail reports, HailTech's 6 AM probability reached an AUC of [X] versus [Y] for climatology and [Z] for a CAPE rule. At the cutoff a fleet manager would use, it caught [P] % of severe-hail days with [F] false alarms a season. It scored the 5 August 2024 storm, which it had never seen, at [Q] %."

### 4.4 Community flag list (Case 4's deliverable)

The probability is for the city box. Communities don't each get a forecast; that would be false precision.

- **Exposure:** kernel density of ICHD reports per community centroid (2005–2022), blended with the case's `hail_track` band. Call it *historical exposure*, never *forecast*.
- **Flag rule, one line:** flag a community when `P(hail day) ≥ p_cut` **and** `exposure ≥ e_cut`.
- **Baselines Case 4 names:** downtown only; flag everyone when the city value is high.
- **Cutoff move:** slide `p_cut` or `e_cut`, count communities that flip, print the ten-line supervisor summary.

Honesty line for the slide: "The model forecasts the day. The exposure map says where hail has historically landed. The flag list is the intersection."

### 4.5 Architecture

```
 ECCC hail reports 2005–2022 ─┐
 (Zenodo, CSV)               │        ┌──────────────────────────────────┐
                              ├──────► │  LABELS: severe-hail day per    │
 UTC→MDT, ≥20 mm, box filter ─┘        │  local day, May–Sep             │
                                       └───────────────┬─────────────────┘
 ERA5 12/18 UTC (CDS, NetCDF) ──► MetPy derivations ──► FEATURES ─────────┤
   CAPE, CIN, shear, SHIP, WBZ, lapse rates, moisture, winds              ▼
                                                  ┌──────────────────────────────┐
 Open-Meteo forecast (today) ──► same derivations │  MODEL: gradient boosting,   │
                                                  │  leave-one-year-out backtest,│
                                                  │  calibrated probability      │
                                                  └──────────────┬───────────────┘
                                                                 ▼
                             ┌──────────────────────────────────────────────────┐
                             │ DASHBOARD (Streamlit + pydeck)                   │
                             │  date picker / today · probability vs baselines  │
                             │  feature panel · community map · cutoff slider   │
                             │  flip count · supervisor summary                 │
                             └──────────────────────────────────────────────────┘
                                        │ optional
                                        ▼
                             ElevenLabs TTS: spoken 6 AM briefing
```

Design rationale for the judges: reanalysis is the only public source with 18 years of history matching the labels; the forecast API gives the same variables for today; gradient boosting because 170 positives cannot train anything deeper and trees handle ERA5's known low bias in CAPE and shear; every feature is a named meteorological quantity, so every probability is explainable.

---

## 5. ElevenLabs (keep thin)

Voice is not native to this problem. Don't force it. Two cheap uses that are defensible:
- **6 AM spoken briefing** for the fleet or emergency-management lead: "HailTech: 38 % chance of severe hail today, highest since July 12. Shear is strong, buoyancy moderate. Flagged: 14 communities, mostly north and northeast. Noon update at 12." One TTS call.
- **Multilingual resident alert** in flagged communities, generated from the same summary.

Build these only after §6's MVP is done. Mention the ElevenLabs prize only if both run live.

---

## 6. Scope and timeline

Clock: Sat ~3 PM to Sun 12 PM.

**MVP (must run end to end by Sat 11 PM):**
1. ICHD → daily labels in the box, UTC converted. Print counts; they must match 170 severe days.
2. Feature pipeline on **Open-Meteo surface history first** (instant, no queue): T, Td, pressure, wind, BLH at 12 UTC. Train, backtest, print AUC. The pipeline is then real even if ERA5 is late.
3. ERA5 lands → MetPy derivations → swap features in. Re-run.
4. Three policies, leave-one-year-out, metrics table, reliability plot.
5. 5 Aug 2024 blind score.
6. Streamlit: date picker, probability vs baselines, community map, cutoff slider, flip count.

**Stretch (only after MVP):** noon-update comparison, cost curve, Open-Meteo "today" live path, TTS briefing, feature-importance panel.

**Hard rule:** no new features after Sat 11 PM. Sunday morning is bug fixes, three rehearsals, screenshots, the Issue.

| When | Track A: Data + model | Track B: Dashboard | Track C: Pitch + ops |
|---|---|---|---|
| **Sat 3–5 PM** | CDS account, submit ERA5 request. ICHD labels. Open-Meteo surface features. | Streamlit skeleton with the 92-community map. | **Confirm case with organizers.** Book a mentor 1-on-1 (ask for an emergency-management or insurance contact). Repo. |
| **Sat 5–8 PM** | First backtest on surface features. ERA5 derivations as data arrives. | Probability panel, baselines table. | Architecture diagram. Slides v1. |
| **Sat 8–11 PM** | ERA5 model, calibration, 5 Aug 2024 score, metrics table. | Cutoff slider, flip count, supervisor summary. | Mentor quote. Freeze scope. |
| **Sat 11 PM–1 AM** | Freeze model. | Polish. **Record backup video.** | Slides v2. |
| **Sun AM** | Bug fixes only. | Bug fixes only. | Rehearse 3×. Screenshots. **Submit the Issue by 11:00 AM.** |

---

## 7. Five-minute pitch

1. **Hook (20 s):** "On 5 August 2024 a hailstorm crossed north Calgary in forty-five minutes and did 3.3 billion dollars of damage. The morning models saw moderate instability and said nothing special. Calgary gets about nine of these days a summer."
2. **Problem and user (40 s):** Fleet yards, transit, airport ground ops, dealers and insurers all have cheap precautions (move it, cover it, warn people) that only pay if someone gives them a credible number by breakfast. Mentor quote here.
3. **Demo (2 min):**
   - **Backtest table:** climatology vs CAPE rule vs HailTech, 18 summers, AUC and CSI.
   - **Pick 5 Aug 2024:** model never saw it. Show the features and the probability.
   - **Cutoff slider:** move it, the community map updates, "N communities flipped," the ten-line summary prints.
   - **(If built) Today:** live forecast → probability → one spoken briefing.
4. **Architecture (40 s):** one diagram. Reanalysis for history, forecast API for today, gradient boosting with every feature a named meteorological quantity.
5. **Commercialization (40 s):** pilot one summer with a fleet operator; SaaS alert for insurers and dealers across Hailstorm Alley; radar nowcast on the roadmap once ECCC volumetric data is licensed. Municipal and insurance software is a Volaris vertical.
6. **Close (20 s):** "A number by breakfast, for the storm the models didn't see coming."

**Demo risk control:** every demo date is pre-computed and cached; the live Open-Meteo call is optional and has a cached fallback; backup video open in another tab.

---

## 8. Likely Q&A

- **"Isn't this just CAPE?"** No. Show the CAPE-only rule in the table. The 5 Aug 2024 case had ~950 J/kg SBCAPE and ~45 kt shear; the model weights shear and CAPE×shear.
- **"Nine positive days a year is tiny. How do you trust it?"** Leave-one-year-out across 18 years, calibrated probabilities, Brier score, reliability plot. We quote ranges, not a single accuracy.
- **"Reports are where people live. Isn't the label biased?"** Yes. Urban box, so bias is smaller than province-wide; rural foothills storms that never reach the city are missed. We say so, and the exposure map is labelled "historical exposure," not forecast.
- **"ERA5 is 25 km. Hail is 1 km."** We predict the environment, not the storm. Day-level, city-box. Neighbourhood precision needs radar, which is the roadmap.
- **"Why not ECCC's own warnings?"** Warnings are issued when storms exist, hours later. This is a 6 AM planning number. Complementary.
- **"Where does the exposure map come from?"** Kernel density of 18 years of reports plus the case's hail-track band. Not insurance claims; we don't have those.
- **"What breaks it?"** Elevated or nocturnal convection, outflow-boundary initiation ERA5 can't see, orographic low-shear days (Prein & Holland flag reanalysis methods as weakest there).

---

## 9. Checklist

- [ ] Case confirmed with organizers: Software, Option B, Case 4, hail focus (**tonight, 11:59 PM latest**)
- [ ] CDS account made, `~/.cdsapirc` written, ERA5 request submitted
- [ ] Python certificate fix applied on Macs
- [ ] ICHD labels built; 170 severe days reproduced
- [ ] Surface-feature backtest running (fallback path proven)
- [ ] ERA5 features derived; model, calibration, metrics table
- [ ] 5 Aug 2024 scored blind
- [ ] Community map, cutoff slider, flip count, supervisor summary
- [ ] Architecture diagram
- [ ] Mentor or industry quote captured
- [ ] Backup demo video recorded
- [ ] GitHub Issue on `nagusubra/industry-hackathon-lab`: 2–5 screenshots, video link, Option B Case 4, data citations (**before Sun 12:00 PM, aim 11:00 AM**)

---

## Data citation

Environment and Climate Change Canada and Northern Hail Project, *Integrated Canadian Hail Database (2005–2022)* v1.0.0, Zenodo, https://doi.org/10.5281/zenodo.8015924. Hersbach et al., *ERA5 hourly data on single levels and pressure levels*, Copernicus Climate Data Store. Open-Meteo forecast and historical APIs (CC BY 4.0). The City of Calgary, Open Calgary, community boundaries (centroids in the Case 4 seed). Hail-track band: scenario label from the hackathon case, reconstructed from public reporting of the 5 Aug 2024 storm; not insurance data.

## Fallbacks

- **ERA5 never arrives:** ship the Open-Meteo surface-feature model. Weaker AUC, same pipeline, same demo. Say why.
- **Model shows no skill over climatology:** present it honestly as a negative result with the feature analysis, and lean on the exposure map and cutoff loop for Case 4's deliverable. Judges reward a clean backtest over a hidden one.
