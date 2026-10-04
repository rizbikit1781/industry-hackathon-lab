# HailTech

**Hail protection for outdoor lots in Calgary.** HailTech tells businesses with property parked outside (car dealers, rental and airport lots, RV storage, nurseries, transit yards, solar farms) when hail is coming for *their* site, so they can move or cover things in time.

It gives two warnings:

1. **Morning heads-up (6 AM).** A model reads the morning atmosphere and estimates the chance of damaging hail in the Calgary area today. On a risky day, sites put a crew on call and clear covered space.
2. **Storm alert (up to 90 minutes before).** Once a storm forms, HailTech tracks the hail on weather radar every few minutes, projects where it is heading, and alerts each site by name: *Storm approaching → Get ready → Act now → Stay inside*. Sites outside the storm's path are told they can carry on.

IEEE YP Industry Hackathon, Calgary, October 2026 · Software and Computational Math stream · Option B, Case 4 (neighbourhood hail flags), extended with public hail, radar and weather data.

**Product page (interactive replay of the 5 August 2024 storm):** open `site/index.html` in a browser. It is self-contained and works offline.

---

## Results

### Storm alert: replay of 5 August 2024

On 5 August 2024 a hailstorm caused about $3 billion of insured damage in north Calgary in under an hour. We replayed that evening using only the radar data available at each moment, for 23 real Calgary businesses.

| | |
|---|---|
| Businesses hit by hail (radar hail ≥ 30 mm) that were warned first | **7 of 7** |
| Notice before the hail arrived (first alert at 7:12 PM, hail at 8:10 PM) | **about 58 min** |
| Safe time to work before staff had to go inside | **36 min** (5 of 7 sites could finish their protection job) |
| Businesses correctly left alone | **12** |
| False alarms (warned, hail missed) | **4**, all within a few km of the damaging hail |
| Same evening, baselines: persistence / "act when hail is already here" | 0 of 7 warned in time |

Environment Canada's city-wide warning went out at 7:21 PM. HailTech's first alert to the sites that were later hit came at 7:12 PM; that call was close to its threshold and is not something we claim would happen every time. HailTech's value is saying **which** sites are in the path. Official warnings always take precedence.

Two quieter days (4 Aug 2025, 2 Jul 2025) were replayed as false-alarm checks: 2 and 0 false alarms.

### Morning heads-up: tested on 17 summers

Leave-one-year-out backtest, May–September 2006–2022 (2,601 days, 168 days with hail ≥ 20 mm reported in the Calgary area). Each summer is hidden in turn, the model is trained on the rest, and every cutoff is chosen on training years only.

| Method | AUC | Brier | Hail days caught | Heads-ups with no hail |
|---|---|---|---|---|
| Calendar only (monthly rate) | 0.735 | 0.0570 | 35% | 85% |
| Simple humidity rule | 0.802 | 0.0548 | 49% | 78% |
| **HailTech** (surface weather) | **0.854** | **0.0513** | 44% | **67%** |

This table is the version trained on ground-level weather only. A version using the full morning atmosphere (ERA5: storm energy, wind shear, freezing level) is being trained; this README will be updated with its results. The current model gave 5 August 2024 only about a 1-in-9 chance: the morning atmosphere that day looked ordinary, and the storm was driven by winds that strengthened later.

---

## How it works

```
 ECCC hail reports 2005–2022 ──► labels: was there a hail day? ─┐
 ERA5 / Open-Meteo morning weather ──► features ────────────────┼─► gradient-boosted model ─► P(hail day) at 6 AM
                                                                │   (calibrated, leave-one-year-out tested)
 NOAA MRMS radar hail size, 2020–2025 ──► how often each 1 km ──┘
   patch of the city gets hit on a hail day

 Live radar every 2 min (MRMS) ──► find hail cells ─► track motion ─► project 0–90 min (ensemble of paths)
   ──► per-site probability ─► Storm approaching / Get ready / Act now / Stay inside / All clear
   ──► latest time a protection job can safely start
```

- **Why gradient boosting:** 168 hail days cannot train anything deeper, trees handle the known biases in reanalysis weather data, and every input is a named weather quantity, so each forecast can be explained.
- **Why rules for the radar alert:** there are too few timed ground reports to train a nowcast model honestly. Tracking plus projection is transparent and testable.
- **Safety:** HailTech never recommends going outside once a storm is near. When hail is within about 10 km or expected within 15 minutes, sites are told to stay inside (Environment Canada lightning guidance).

Full design: [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md).

---

## Run it

Python 3.10+ (3.11 used). On macOS with python.org Python, run `/Applications/Python 3.11/Install Certificates.command` once or HTTPS downloads fail.

```bash
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
```

### View the results (no downloads needed beyond this repo)

- **Product page:** open `site/index.html`.
- **Dashboard** (needs the processed data, see below): `.venv/bin/streamlit run app/streamlit_app.py`

### Rebuild everything from public data

Raw data is not committed. Run these in order:

```bash
# 1. Hail reports (ECCC Integrated Canadian Hail Database, Zenodo 8015925)
mkdir -p data/raw
curl -L -o data/raw/hail.csv "https://zenodo.org/api/records/8015925/files/integrated_canadian_hail_db.csv/content"
.venv/bin/python -m hailday.labels

# 2. Radar hail size per day, 2020–2025 (NOAA MRMS, anonymous AWS + Iowa State archive)
.venv/bin/python scripts/fetch_mesh.py
.venv/bin/python -m hailday.mesh

# 3. Morning weather
.venv/bin/python scripts/fetch_openmeteo.py            # ground-level history, ~20 min (rate-limited)
.venv/bin/python scripts/request_era5.py               # optional, needs a Copernicus CDS account (see below); hours
.venv/bin/python -c "from hailday.era5 import build_all; build_all()"

# 4. Train, test and score
.venv/bin/python scripts/train.py --source openmeteo --build   # or --source era5
.venv/bin/python scripts/score.py --source openmeteo

# 5. Radar replays and checks
.venv/bin/python scripts/replay_nowcast.py             # 5 Aug 2024 (and --event for other days)
.venv/bin/python scripts/validate_nhp.py

# 6. Product page and tests
.venv/bin/python scripts/build_site.py
.venv/bin/pytest -q
```

**ERA5 access:** register at https://cds.climate.copernicus.eu, copy your API token from your profile, and accept the licence on both the single-levels and pressure-levels dataset pages. Put the token in `~/.cdsapirc` (never in this repo):

```
url: https://cds.climate.copernicus.eu/api
key: <your-token>
```

---

## Repository layout

| Path | What it does |
|---|---|
| `hailday/` | Morning model: labels, features (Open-Meteo, ERA5 indices), model and backtest, radar hit rates, per-site decisions, value curves |
| `nowcast/` | Storm alert: MRMS download, hail-cell tracking, 0–90 min projection, alert states, safe-time-to-work |
| `scripts/` | Command-line steps listed above |
| `app/` | Streamlit dashboard: storm story, morning briefing, replay, backtest, community flags (Case 4), how it works |
| `site/` | Product page template and generated `index.html` |
| `data/` | Small committed inputs: 23 sites with assumed costs and job times, Case 4 community table, Calgary basemap, Environment Canada warning timeline for 5 Aug 2024 |
| `docs/` | Architecture, strategy, hail research notes |
| `tests/` | 26 tests |

---

## Data sources and licences

| Data | Source | Licence | Used for |
|---|---|---|---|
| Hail reports 2005–2022 | ECCC Integrated Canadian Hail Database, [Zenodo 8015925](https://zenodo.org/records/8015925) | CC BY 4.0 | Morning-model labels |
| Radar hail size (MESH) and radar products | NOAA MRMS, `noaa-mrms-pds` on AWS; Iowa State mtarchive | Public domain | Storm alert, per-site hit rates, truth for replays |
| Reanalysis weather | ERA5, Copernicus Climate Data Store | Copernicus licence, attribution | Morning-model features |
| Surface weather history and forecast | Open-Meteo | CC BY 4.0 | Morning-model features, live inputs |
| Environment Canada warnings, 5 Aug 2024 | ECCC CAP alerts as archived by Alberta Emergency Alert | Government of Canada open terms | Comparison baseline |
| Damage surveys, 5 Aug 2024 | Northern Hail Project, Western University | CC BY-NC 4.0 | Independent check only; not used for training |
| Business locations, city boundary, roads | Open Calgary (Open Government Licence – City of Calgary); OpenStreetMap (ODbL) | As stated | Sites and map |
| Community table | Hackathon Case 4 seed data | As provided | Community flag view |

---

## Limits

- **The morning heads-up missed 5 August 2024.** Some storms are driven by winds that strengthen during the day and do not show at 6 AM.
- **Radar projection assumes storms keep their speed, direction and strength.** They can turn, split or die; beyond about 60 minutes the alert is a rough guide.
- **Hail size is a radar estimate**, which tends to run high. A site counts as hit at 30 mm radar hail, not 20 mm.
- **Only three storm days were replayed**, so the false-alarm rate is not settled.
- **Costs and job times per site are our estimates**, set per type of business, not supplied by the businesses.
- **Ground reports come from where people live**, so storms over open country are under-reported in the labels.

---

HailTech never tells anyone to go outside during a storm. Environment Canada watches and warnings always come first.
