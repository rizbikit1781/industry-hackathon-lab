# SnowTech web console

Next.js (App Router, TypeScript, Tailwind v4) front end for the SnowTech dispatch engine.
It replaces the Streamlit dashboard for demos.

| Page | What it shows |
|---|---|
| `/` Live ops | Full-height MapLibre map of today's plan from the FastAPI engine (crew routes, one colour per crew; open tickets coloured by exposure tier; depots; voice tickets pulsing). Side panel: KPI tiles, disruption buttons (3 crews out / restore / surge) with jobs moved and replan seconds, live feed of voice reports with their `reason`, crew list with stops, tickets, km and finish time. Polls `GET /plan` and `GET /metrics` every 2.5 s and toasts new voice tickets. Embeds the ElevenLabs intake agent widget (agent id read from `../voice/agents.json`). |
| `/replay` | Storm-week replay (Nov 25 - Dec 1, 2025): policy toggle (FIFO / SnowTech / + disruption), day slider, the map for that day, day stats, per-day charts, and the full three-policy comparison (small-multiple bars + table), including where SnowTech does worse. |
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

- `/api/*` is a Next.js rewrite to `http://127.0.0.1:8000/*` (override with `SNOWTECH_API_URL`; the old
  `CIVICSIGNAL_API` still works), so the
  Python API needs no CORS changes. `POST /tickets` and `POST /disruption` are excluded from the
  proxy: tickets only come from the ElevenLabs webhook.
- `POST /api-internal/disruption` is a server route that forwards `{crews_out}` or `{surge:true}` to
  the API with the `X-CivicSignal-Key` header. The key (`CIVICSIGNAL_KEY`) is read server-side
  from `process.env`, else `../.env`, and never reaches the browser.
- `/api-internal/replay/summary` and `/api-internal/replay?policy=&day=` read `../data/results.json`
  at request time (re-read when the file changes), so a rerun of `scripts/run_sim.py` shows up without
  a rebuild. When the parent file is absent (Vercel deploys only `web/`) they read `web/data/results.json`,
  which `predev`/`prebuild` refresh from `../data/results.json` (committed so a fresh clone deploys).
- The ElevenLabs intake agent id comes from `SNOWTECH_INTAKE_AGENT_ID`, else `../voice/agents.json`.
- Crew routes use the `geometry` field (road network, `[lon, lat]` list) when the engine provides
  it, else straight lines between stops.

## Empty and error states

No data is fabricated. If the API is down the console says so ("API not reachable. Start uvicorn")
and keeps the last plan it received; if `data/results.json` is missing the replay page says how to
generate it.

## Deploy (Vercel)

`web/` is linked to the Vercel project `snowtech` (team `caelanxs-projects`); production URL
https://snowtech-phi.vercel.app. Production env vars (all server-side, none `NEXT_PUBLIC_`):

| Var | Purpose |
|---|---|
| `SNOWTECH_API_URL` | FastAPI engine base URL (rewrites + `/api-internal/disruption`). Baked into the rewrites at build time, so a change needs a redeploy. |
| `CIVICSIGNAL_KEY` | Shared secret sent as `X-CivicSignal-Key` on disruptions. |
| `SNOWTECH_INTAKE_AGENT_ID` | ElevenLabs intake agent id for the widget. |

Point the console at a new backend and redeploy (from `web/`):

```bash
vercel env update SNOWTECH_API_URL production --value https://NEW-API-HOST --yes && vercel deploy --prod --yes
```

Locally none of these are needed: defaults are `http://127.0.0.1:8000`, `../.env` and `../voice/agents.json`.
