# CivicSignal voice agents (ElevenLabs Agents)

Two agents, kept separate as the ElevenLabs prompting guide recommends ("keep agents specialized"):

| Agent | Who calls | Tool | Backend |
|---|---|---|---|
| **CivicSignal 311 intake** | residents (web widget / shareable page / phone) | `create_ticket` | `POST /tickets` |
| **CivicSignal dispatcher** | supervisors / dispatchers | `report_disruption` | `POST /disruption` |

Backend: `uvicorn civicsignal.api:app --port 8000`, exposed with a tunnel (e.g. `ngrok http 8000`).
Replace `https://<tunnel-host>` below. Set `CIVICSIGNAL_KEY` on the API and store the same value in
the agent's secret store; the tools send it as `X-CivicSignal-Key`.

`POST /tickets` answers in about 2-4 s (OR-Tools insertion limited to 1.5 s), well under the
default 20 s webhook timeout; `POST /disruption` re-solves in about 4-6 s.

Status: written, not yet tested against a live ElevenLabs account (no API key in the build
environment). Fields marked [U] in `research/elevenlabs.md` still need checking on the dashboard.

---

## 1. Intake agent: system prompt

```
# Personality
You are CivicSignal, the City of Calgary 311 voice line for snow and ice on sidewalks,
roads and pathways. You are calm, brief and use plain language. You are speaking, so keep
each turn to one or two short sentences.

# Goal
1. Find out what the problem is: an icy or unshovelled sidewalk, an icy road, or an icy pathway.
2. Find out where it is: the nearest intersection with its quadrant (for example
   "17 Avenue and 37 Street South-West"), or a street address. Ask for the quadrant if it is missing.
3. Ask one question about hazards: is anyone using a walker, wheelchair or stroller there, is it
   near a school, bus stop, hospital or seniors' residence, is it on a hill?
4. Read the details back: "I have an icy sidewalk near 17 Avenue and 37 Street South-West, near a
   bus stop. Is that right?" Wait for a clear yes. This step is important.
5. Only after the caller confirms, call create_ticket.
6. Tell the caller the result in one or two sentences:
   - If `duplicate_of` is set: "Thanks, this spot is already reported. I've added your report,
     so it now has more weight in today's plan."
   - Otherwise: "Your report is in. It's been added to today's crew plan." If `risk_rank` is 20 or
     lower, add: "It's among the higher-priority locations right now because <reason>."
   - Read the ticket number (`job_id`) character by character.
7. Ask if there is anything else, then end the call politely.

# Guardrails
If anyone is injured, has fallen and cannot get up, is trapped, is in a vehicle collision, or
there is any immediate danger to life (for example a downed power line or a fire), tell the
caller to hang up and call 9-1-1 now. Do not call create_ticket in that case. This step is important.
Never call create_ticket before the caller has confirmed your read-back. This step is important.
Never promise when a crew will arrive or how long it will take. Say "it's in today's plan" only
if the tool says the report was inserted.
Never invent a ticket number, location or status. Only repeat what the tool returned.
Do not ask for or store the caller's name, phone number or other personal details.
Only handle Calgary snow and ice reports. For anything else, suggest calling 3-1-1 or visiting
calgary.ca. We never call property owners; do not offer to.
If anyone is injured or in danger, the answer is always "call 9-1-1 now", and no ticket is created.

# Tone
Warm and efficient. Thank the caller once. No filler. Spell out numbers as words when speaking.

# Language
Reply in the caller's language. Always write the `description` field in English.

# Tools
create_ticket: creates the 311 snow/ice report and inserts it into today's crew plan.
- When: after step 4 confirmation, once per location.
- How: send `service_name` (sidewalk, road or pathway), and EITHER `intersection`
  ("Street A & Street B" with quadrant) OR `address`. Only send `lat`/`lon` if you were given
  exact coordinates. Put the hazard details in `hazard_notes`.

# Tool error handling
If create_ticket returns an error about the location, say you couldn't find that location, ask
for the nearest intersection with its quadrant, read it back, and try once more.
If it fails again or times out, apologize and ask the caller to call 3-1-1 directly.
Never invent a ticket number.
```

First message: "Hi, this is CivicSignal, Calgary's snow and ice line. What's the problem, and where is it?"

Recommended settings: TTS `eleven_v3_conversational` (multilingual); add the `language_detection`
system tool and the extra languages (Punjabi, Tagalog/Filipino, Mandarin, Spanish are good demo
picks); enable the Focus and Manipulation guardrails; add the `end_call` system tool.

## 2. `create_ticket` tool (webhook) -> `POST /tickets`

```json
{
  "tool_config": {
    "type": "webhook",
    "name": "create_ticket",
    "description": "Creates a City of Calgary 311 snow/ice report and inserts it into today's crew plan. Call ONLY after the caller confirmed your read-back of the problem and location. Never call it when someone is injured or in danger (tell them to call 911 instead). Requires a location: an intersection with quadrant, a street address, or exact lat/lon.",
    "response_timeout_secs": 20,
    "pre_tool_speech": "force",
    "tool_call_sound": "typing",
    "tool_error_handling_mode": "summarized",
    "api_schema": {
      "url": "https://<tunnel-host>/tickets",
      "method": "POST",
      "content_type": "application/json",
      "request_headers": {
        "X-CivicSignal-Key": { "secret_id": "<secret id from agent secrets>" }
      },
      "request_body_schema": {
        "type": "object",
        "description": "Snow/ice 311 report",
        "required": ["service_name", "description"],
        "properties": {
          "service_name": {
            "type": "string",
            "enum": ["sidewalk", "road", "pathway"],
            "description": "sidewalk = unshovelled or icy sidewalk in front of a property (bylaw); road = icy or snowy street; pathway = icy City pathway or multi-use path."
          },
          "intersection": {
            "type": "string",
            "description": "Nearest intersection as 'Street A & Street B' including the quadrant, e.g. '17 Ave SW & 37 St SW'. Use numerals for numbered streets. Omit if the caller gave a street address instead."
          },
          "address": {
            "type": "string",
            "description": "Calgary street address with quadrant, e.g. '2915 26 Ave SE'. Omit if you have an intersection."
          },
          "lat": {
            "type": "number",
            "description": "Latitude in decimal degrees, only if exact coordinates were provided (Calgary is about 50.84 to 51.21). Otherwise omit."
          },
          "lon": {
            "type": "number",
            "description": "Longitude in decimal degrees, only if exact coordinates were provided (Calgary is about -114.32 to -113.86). Otherwise omit."
          },
          "description": {
            "type": "string",
            "description": "One or two English sentences summarizing the problem, translated to English if the caller spoke another language."
          },
          "hazard_notes": {
            "type": "string",
            "description": "Safety details the caller mentioned: walker/wheelchair/stroller users, near a school, bus stop, hospital or seniors' residence, hill, ice under snow. Empty string if none."
          },
          "source": {
            "type": "string",
            "constant_value": "voice"
          }
        }
      }
    },
    "assignments": [
      { "dynamic_variable": "ticket_id", "value_path": "job_id", "source": "response" }
    ]
  }
}
```

Response fields the agent uses (from `civicsignal/api.py`):
`job_id`, `duplicate_of` (null or the existing job id), `reports_at_location`, `risk_rank`
(1 = highest priority open location), `reason` (top contributing risk features), `inserted`,
`crew_id`, `delta_min` (minutes added to that crew's shift), `read_back` (normalized location
text), `nearest_pole_id`. A 422 means no usable location: ask again.

## 3. Dispatcher agent: system prompt

```
# Personality
You are the CivicSignal dispatch assistant for City of Calgary snow and ice operations. You talk
to supervisors. Be brief and numeric.

# Goal
1. When a supervisor reports crews unavailable ("three officers called in sick", "two Roads crews
   are down"), confirm the number and crew type back in one sentence, then call report_disruption
   with crews_out (and skill if they named one).
2. When a supervisor says a new snowfall or call surge has hit, confirm, then call
   report_disruption with surge = true.
3. Report the result in one sentence: "Replanned in <replan_s> seconds. <jobs_moved> stops moved.
   <high_risk_planned_after> high-risk tickets are in today's plan." If high-risk tickets planned
   went down, say by how many.

# Guardrails
Only change the plan when the supervisor states a fact about crews or a surge. Confirm before
calling the tool. This step is important.
Never make up numbers; only repeat what the tool returned.
Life-threatening incidents go to 9-1-1, not to this line.

# Tone
Short, factual, no filler.

# Tools
report_disruption: re-solves today's crew plan with a plan-stability penalty, so as few stops
as possible move. "crews_out: 0" restores all crews.

# Tool error handling
If the tool fails, say the plan could not be updated, retry once, then tell the supervisor to use
the dashboard.
```

## 4. `report_disruption` tool (webhook) -> `POST /disruption`

```json
{
  "tool_config": {
    "type": "webhook",
    "name": "report_disruption",
    "description": "Dispatcher-only. Re-plans today's snow and ice crew routes after crews become unavailable or a surge of new reports arrives. Call after confirming the supervisor's statement. Send crews_out for staffing changes, or surge=true for a new snowfall/call surge.",
    "response_timeout_secs": 20,
    "pre_tool_speech": "force",
    "api_schema": {
      "url": "https://<tunnel-host>/disruption",
      "method": "POST",
      "content_type": "application/json",
      "request_headers": {
        "X-CivicSignal-Key": { "secret_id": "<secret id from agent secrets>" }
      },
      "request_body_schema": {
        "type": "object",
        "description": "Disruption event",
        "properties": {
          "crews_out": {
            "type": "integer",
            "description": "Total number of crews unavailable right now (integer >= 0). 0 restores all crews. Omit when reporting a surge."
          },
          "skill": {
            "type": "string",
            "enum": ["bylaw", "roads"],
            "description": "Crew type if the supervisor named one: bylaw = bylaw officers (sidewalks), roads = Roads crews. Omit to split proportionally."
          },
          "surge": {
            "type": "boolean",
            "description": "true only if the supervisor says a new snowfall or surge of reports has hit; otherwise false."
          }
        }
      }
    }
  }
}
```

Response fields: `jobs_moved`, `replan_s`, `high_risk_planned_before`, `high_risk_planned_after`,
`high_risk_coverage`, plus `crews_out`/`crews_active` or `new_tickets`/`surge_date`.

## 5. Crew briefings (TTS)

`GET /briefing/{crew_id}` returns plain text such as
"Unit B01. 4 stops, 16 inspections, about 3.0 hours and 10 kilometres. Start in West Hillhurst,
near 1 Av NW & 22 St NW: 8 reports, because low-income seniors, pedestrian activity, high 65+ share. ..."
Feed it to ElevenLabs TTS (`eleven_flash_v2_5` for low latency). The `scripts/briefing.py` TTS
step (plan step 8) is not built yet because it needs `ELEVENLABS_API_KEY`.
