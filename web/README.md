# CivicSignal web console

Next.js (App Router, TypeScript, Tailwind v4) front end for the CivicSignal dispatch engine.
It replaces the Streamlit dashboard for demos.

| Page | What it shows |
|---|---|
| `/` Live ops | Full-height MapLibre map of today's plan from the FastAPI engine (crew routes, one colour per crew; open tickets coloured by exposure tier; depots; voice tickets pulsing). Side panel: KPI tiles, disruption buttons (3 crews out / restore / surge) with jobs moved and replan seconds, live feed of voice reports with their `reason`, crew list with stops, tickets, km and finish time. Polls `GET /plan` and `GET /metrics` every 2.5 s and toasts new voice tickets. Embeds the ElevenLabs intake agent widget (agent id read from `../voice/agents.json`). |
| `/replay` | Storm-week replay (Nov 25 - Dec 1, 2025): policy toggle (FIFO / CivicSignal / + disruption), day slider, the map for that day, day stats, per-day charts, and the full three-policy comparison (small-multiple bars + table), including where CivicSignal does worse. |
| `/about` | How it works, in plain words: data, risk, solver, replan, voice, plus honest limits. |

## Run

```bash
# 1. the engine (from civicsignal/)
.venv/bin/uvicorn civicsignal.api:app --port 8000

# 2. the console (from civicsignal/web/)
npm install
npm run dev          # http://127.0.0.1:3000
# or: npm run build && npm start
```

`predev`/`prebuild` copy MapLibre's web worker into `public/maplibre/` (MapLibre v6 loads it as a
sibling module, which bundlers cannot resolve).

## Data flow

- `/api/*` is a Next.js rewrite to `http://127.0.0.1:8000/*` (override with `CIVICSIGNAL_API`), so the
  Python API needs no CORS changes. `POST /tickets` and `POST /disruption` are excluded from the
  proxy: tickets only come from the ElevenLabs webhook.
- `POST /api-internal/disruption` is a server route that forwards `{crews_out}` or `{surge:true}` to
  the API with the `X-CivicSignal-Key` header. The key is read server-side from `../.env`
  (`CIVICSIGNAL_KEY`) and never reaches the browser.
- `/api-internal/replay/summary` and `/api-internal/replay?policy=&day=` read `../data/results.json`
  at request time (re-read when the file changes), so a rerun of `scripts/run_sim.py` shows up without
  a rebuild.
- Crew routes use the `geometry` field (road network, `[lon, lat]` list) when the engine provides
  it, else straight lines between stops.

## Empty and error states

No data is fabricated. If the API is down the console says so ("API not reachable. Start uvicorn")
and keeps the last plan it received; if `data/results.json` is missing the replay page says how to
generate it.
