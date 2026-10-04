# SnowTech: team context

Last updated: Sun Oct 4, 2026, 12:45 PM MT. **Submitted.** Judging runs 1:00–4:00 PM, with an 8-minute slot per team: a 5-minute pitch and 3 minutes of Q&A.

## What SnowTech is

SnowTech gets Calgary's snow and ice crews to the most dangerous ice first:
- Residents report by voice to an ElevenLabs agent.
- An OR-Tools solver re-plans every bylaw officer and Roads crew route on the real road network in seconds.
- The submission is Option B, Software and Computational Math, Case 1 (311 Work-Order Dispatch). The project started as "CivicSignal", so code names still say `civicsignal`.

## Live links

| What | Where |
|---|---|
| Live console (demo from here) | https://snowtech-phi.vercel.app |
| Engine API | https://api-production-3bf1.up.railway.app (`/health`, `/plan`) |
| Voice agent (resident intake) | https://elevenlabs.io/app/talk-to?agent_id=agent_5101m423jswyf5eaxdgc9zt6yy9a |
| Voice agent (dispatcher) | https://elevenlabs.io/app/talk-to?agent_id=agent_2301m423jvcwf0rbrtzw7jg3y8sv |
| Narrated demo video | `civicsignal/demo/snowtech-demo-narrated.mp4` (64 s) |
| Screenshots | `civicsignal/demo/screenshots/` |
| Recording script | `civicsignal/demo/quicktime-shot-list.md` |

None of this needs a laptop running: the site is on Vercel, the engine is on Railway, and the agents are on ElevenLabs. The Vercel, Railway and ElevenLabs accounts are Caelan's.

## Headline numbers

These come from a replay of Calgary's real storm week, Nov 25 – Dec 1, 2025. Every policy gets the same crews.

| | Oldest-first | SnowTech |
|---|---|---|
| High-risk tickets served within 48 h | 13.4% | **42.9%** (3.2×) |
| Road km driven | 8,652 | **2,848** (−67%) |
| Low-risk tickets served in the week | **57.1%** | 35.4% |
| Slowest 10% of tickets (days) | **5** | 6 |

Other numbers for the pitch:
- **Base case per season:** about $183k saved (range $10k–$351k), 819 crew-hours freed, 15,100 L of fuel and 40 t of CO₂ avoided. At about $0.10 per resident, Calgary's licence would be roughly $130k, so it pays for itself.
- **The problem:** every winter since 2018, the median icy-sidewalk complaint has taken 5–11 days to close, and 1 in 10 has taken 17–30 days. That's from 104,450 complaints in Open Calgary 311 data.

## Demo flow for judging (about 2 minutes of the pitch)

1. **Storm-week replay:** toggle FIFO vs SnowTech. Say "13 percent vs 43 percent, 8,652 km vs 2,848."
2. **Live ops:** click **Talk to SnowTech 311** and say "Snow on the sidewalk by the bus loop at the University of Calgary, a man in a wheelchair can't get through." Say **yes** to the read-back. The ticket lands on the map, ranked near the top. Then say "That's all" and the agent hangs up.
3. **Disruption:** click **3 crews out**. It re-plans in about 4 s. Then click **Restore crews**.
4. **Close on How it works:** "A language model listens, a solver decides, and every decision comes with its reasons."

**Before your slot, reset the board** so test tickets disappear. Anyone with the link can press the disruption buttons. Caelan runs, from the deploy copy:
```
railway restart --service api -y     # Ctrl+C after ~10 s; the restart still happens
```
**Backup:** if the Wi-Fi dies, play the narrated video, which works offline.

## Voice agent tips

- **Locations it understands:**
  - numbered intersections with a quadrant ("17 Avenue and 37 Street South-West")
  - street addresses
  - landmarks: schools, universities, hospitals, LRT stations, libraries, seniors' residences, plus malls and parks via OpenStreetMap
- **Ambiguous names:** for names like "Mount Royal", it asks "did you mean A or B?"
- **Implied hazards:** a school, university or hospital landmark automatically counts as "near a school" or "near a hospital". The agent does not ask about hazards. It records the ones the caller mentions (wheelchair, walker, bus stop, a fall), and those move the ticket up.
- **Asking for a moment:** say "give me a second." It waits silently, and only hangs up after 3 minutes of total silence.
- **Emergencies:** anything life-threatening gets "call 9-1-1", and no ticket is created.

## Where the code is

| Folder | What |
|---|---|
| `civicsignal/civicsignal/` | Python engine: `ingest`, `features`, `risk`, `dedupe`, `roads` (OSM routing), `solver` (OR-Tools), `sim` (replay), `landmarks`, `api` (FastAPI) |
| `civicsignal/web/` | Next.js console: live ops, replay, how it works, and the `@elevenlabs/react` voice panel |
| `civicsignal/voice/agent.md` | Both agents' prompts and tool definitions; `scripts/setup_voice.py` pushes them to ElevenLabs |
| `civicsignal/scripts/` | `pull_data.py`, `build_roads.py`, `run_sim.py`, `setup_voice.py` |
| `civicsignal/research/` | ElevenLabs notes, Calgary snow-ops research, seniors' residences |
| `civicsignal/README.md` | Full setup for running it locally ("Setup for teammates") |

**One thing to know:** the cloud deployment lives on Caelan's local `deploy` branch, which isn't in this repo yet. That branch has:
- the Dockerfile and bundled data for Railway
- env-var config for Vercel
- this morning's voice fixes: "McEwen Hall" speech-to-text spellings, landmark-implied hazards, no hazard questions, and a stricter read-back

This branch has everything else.

## Likely judge questions

- **"You lose on low-risk tickets and the slowest 10%."** Crews have about half the capacity they need, so SnowTech triages. Oldest-first caps the oldest wait; we put the riskiest ice first. We show this trade-off openly on the replay page.
- **"Is the pedestrian data validated?"** No, and it's our weakest input. It's checked against only 12 City counters (rank correlation 0.16). Crosswalk density alone tracks better (0.41), so that's the first pilot fix.
- **"Why are historical tickets at community centres?"** That's how the public 311 data is published. Voice reports carry the exact spot, which is part of the pitch.
- **"Is this a chatbot?"** No. Remove the voice and the solver still makes the plan. Voice is the way in.
- **"Who's the customer?"** The City of Calgary first, as a pilot district in winter 2026–27. Then 100+ Canadian cities with 50,000+ residents.

## Rules for the repo

- **Never commit `.env`.** It holds the ElevenLabs key and the webhook secret. Ask Caelan privately if you need them.
- **Run `pytest -q tests` before pushing engine changes.** 32 tests should pass.
