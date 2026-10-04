# SnowTech: deploy branch context

Last updated: Sun Oct 4, 2026, 12:50 PM MT.

This is the **`deploy` branch**. It's a git worktree at `~/code/hackathon/civicsignal-deploy`, and SnowTech runs in the cloud from it. `master` (`~/code/hackathon/civicsignal`) is the laptop version and was deliberately left untouched. The team copy (branch `civicSignal` of `rizbikit1781/industry-hackathon-lab`) has its own CONTEXT.md covering the product, numbers, demo flow and Q&A.

## What runs where

| Piece | Host | Address | Account |
|---|---|---|---|
| Web console (Next.js) | Vercel project `snowtech` | https://snowtech-phi.vercel.app | Vercel `caelanx` |
| Engine API (FastAPI) | Railway project `snowtech`, service `api` (1 GB, 2 vCPU) | https://api-production-3bf1.up.railway.app | Railway, Caelan Neumann |
| Voice agents | ElevenLabs (intake + dispatcher) | webhooks to the Railway API | ElevenLabs, Caelan |

Nothing here depends on the laptop. The site proxies `/api/*` to Railway, and the agents call Railway directly.

## What this branch adds on top of master

1. **Railway packaging:**
   - `Dockerfile` (python:3.11-slim + libgomp1), `.dockerignore`, `.railwayignore`, `railway.json` (health check on `/health`).
   - Runtime data force-added to git (about 45 MB): `data/layers/*`, `data/raw/parcel_address.csv`, `data/poles.csv`, `data/features_by_cell.parquet`, `data/roads/calgary_drive.npz`, `data/roads/matrix_cache.npz`. The 48 MB raw graphml is left out because only rebuilds need it.
2. **Vercel config in `web/`:** settings come from env vars, falling back to the old local files, so local runs behave the same.
   - `SNOWTECH_API_URL`, used by the proxy and server routes. It's fixed at build time, so changing it needs a redeploy.
   - `CIVICSIGNAL_KEY`, server-side only.
   - `SNOWTECH_INTAKE_AGENT_ID`.
   - `web/data/results.json` is a bundled copy of the replay data, refreshed by `predev`/`prebuild`. `vercel.json` forces the Next.js framework.
3. **Voice fixes from the 12:30 live test** (not in master or the team repo yet):
   - Speech-to-text spellings of MacEwan Hall ("McEwen Hall", "Mc Ewan") now resolve to the University of Calgary (`civicsignal/landmarks.py`).
   - A landmark's type now implies a hazard: school, university, hospital, seniors' residence or transit station (`risk.place_hazards`, used in `api.create_ticket`). The reason reads "location near school".
   - The intake prompt no longer asks about hazards, and only a clear yes to the read-back files a ticket. "No", "it's not" and silence never count (`voice/agent.md`).
4. `voice/agents.json` has `base_url` set to the Railway API.

## Common commands (run from this folder)

```bash
# Reset the demo board (clears voice tickets and disruptions). The CLI may hang: Ctrl+C after ~10 s.
railway restart --service api -y

# Redeploy the engine after code changes. --no-gitignore is required, or the data is dropped.
railway up --no-gitignore --service api --ci -m "redeploy"

# Push agent prompt/tool changes from voice/agent.md to ElevenLabs (points them at Railway)
../civicsignal/.venv/bin/python scripts/setup_voice.py https://api-production-3bf1.up.railway.app

# Redeploy the web console (from web/)
cd web && vercel deploy --prod --yes

# Point the web console at a different API, then redeploy (from web/)
vercel env update SNOWTECH_API_URL production --value https://NEW-API-HOST --yes && vercel deploy --prod --yes

# Tests (32 should pass)
../civicsignal/.venv/bin/python -m pytest -q tests
```

## Switching the voice agents back to the laptop

The agents can point at only one API at a time. To demo from `localhost:3000` instead:
1. Start the laptop API and a tunnel (master README, steps 5–6).
2. Run `cd ~/code/hackathon/civicsignal && .venv/bin/python scripts/setup_voice.py https://<tunnel>.trycloudflare.com`.

Note that master's `voice/agent.md` doesn't have the 12:30 prompt fixes, so running it from master pushes the older prompt. Run `setup_voice.py` from this folder to keep the fixes.

## Secrets

- `.env` in this folder is a local copy of master's, holding `ELEVENLABS_API_KEY` and `CIVICSIGNAL_KEY`. It's gitignored, so never force-add it.
- On Railway, `CIVICSIGNAL_KEY` is a service variable. On Vercel, `CIVICSIGNAL_KEY`, `SNOWTECH_API_URL` and `SNOWTECH_INTAKE_AGENT_ID` are production env vars marked sensitive.
- The ElevenLabs key was pasted into a chat on Oct 3. Rotate it after the hackathon (elevenlabs.io/app/settings/api-keys), then update `.env` in both folders.

## Known limits

- **Public disruption buttons:** anyone with the site link can press them and change the shared live plan. Reset before presenting.
- **Memory:** the engine keeps state in memory. Any restart or redeploy resets the board, and peak use was about 420 MB of the 1 GB limit.
- **Nominatim fallback:** used for landmarks not in the local index (malls, parks). It takes the first in-Calgary result, with no confidence check.
- **Railway config:** the CLI warns that `railway.json` is deprecated from Dec 1, 2026.

## After the hackathon

- Merge the voice fixes (item 3 above) into master and the team repo.
- Rotate the ElevenLabs key.
- Make the agents private or require authentication, so nobody mistakes them for the real City 311 line.
- Decide whether to keep or delete the Railway and Vercel projects. Billing so far is $0.
