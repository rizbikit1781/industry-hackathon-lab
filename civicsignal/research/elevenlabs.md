# ElevenLabs research for CivicSignal (voice 311 snow/ice dispatch)

Researched 2026-10-03 against current docs. Note: docs moved from `/docs/agents-platform/...` and `/docs/conversational-ai/...` to `/docs/eleven-agents/...`. The product is now called **ElevenAgents**. Appending `.md` to any docs URL returns raw markdown, which is useful for scripting. Index: https://elevenlabs.io/docs/llms.txt

Legend: **[V]** verified in an official doc or pricing page today. **[U]** unverified or inferred, so check it in the dashboard.

---

## TL;DR for decisions

| Topic | Fact | Source |
|---|---|---|
| Creator plan | $22/mo ($11 first month), **121,000 credits** (not 131k) [V] | https://elevenlabs.io/pricing |
| Creator agent minutes | **275 call minutes/mo included, 10 concurrent calls** [V] | https://elevenlabs.io/pricing/agents |
| Overage | $0.08/min. Burst (over the concurrency limit) costs $0.16/min [V] | https://elevenlabs.io/pricing/agents |
| Burst cap | Up to 3x plan concurrency (Creator: 10 to **30**), off by default, enabled per agent [V] | https://elevenlabs.io/docs/eleven-agents/guides/burst-pricing |
| Billing model | "ElevenAgents plans are billed by call minutes, not by the shared credit pool". LLM is billed separately on top [V] | https://elevenlabs.io/pricing/agents (FAQ) |
| Silence | 95% discount on silences over 10 s. Billing counts connection duration, so an open widget tab keeps burning minutes [V] | https://elevenlabs.io/docs/help-center/product/eleven-agents/how-much-does-eleven-agents-cost.md |
| Public share | Widget embed and a "shareable page" (public landing link) both exist. **The agent must be public with auth disabled** [V] | https://elevenlabs.io/docs/eleven-agents/customization/widget |
| Languages | Use **Eleven v3 Conversational** TTS for 70+ languages (Punjabi, Urdu, Filipino, Mandarin, Arabic, Spanish, French). **Cantonese is only in the Eleven v4 family** [V/U, see section 3] | https://elevenlabs.io/docs/overview/models |

**Audience-demo math (Creator):** 10 concurrent calls, or 30 with burst at 2x price. 275 minutes total. If 40 people scan a QR code and each talks for 2 minutes, that's 80 minutes, which fits the quota, but only 10 (or 30 with burst) can be live at once. The rest get rejected unless **call queueing** is enabled (https://elevenlabs.io/docs/eleven-agents/guides/call-queueing). Overage past the included minutes requires Pay-As-You-Go credits (https://elevenlabs.io/docs/help-center/product/eleven-agents/how-much-does-eleven-agents-cost.md) [V]. **[U]** Whether burst works on Creator without PAYG enabled is unverified, so test it before the demo. Also set `platform_settings.call_limits.daily_limit` as a cost guard, and add a domain **Allowlist** (Security tab).

---

## 1. Server (webhook) tools that call our FastAPI backend

Docs: https://elevenlabs.io/docs/eleven-agents/customization/tools/webhook-tools
API ref: https://elevenlabs.io/docs/eleven-agents/api-reference/tools/create (`POST https://api.elevenlabs.io/v1/convai/tools`)

How it works [V]:
- Tool = `type: "webhook"`, `name`, `description`, `api_schema`. The LLM decides **when** to call a tool from its name and description plus the system prompt. It decides **what** to send from each parameter's `description`. "the assistant generates query, body, and path parameters dynamically based on the conversation and parameter descriptions you provide."
- `api_schema` fields: `url` (with `{path_params}`), `method` (GET/POST/PUT/PATCH/DELETE), `path_params_schema`, `query_params_schema` (literal types only), `request_body_schema` (an object schema: `type: "object"`, `properties`, `required`, `description`), `request_headers`, `content_type` (`application/json` default, or form-urlencoded), `auth_connection`, `response_filter` (an allow-list that trims the response before the LLM sees it).
- Each literal property sets **exactly one** of: `description` (the LLM fills it), `dynamic_variable` (filled from a variable), `constant_value`, `is_system_provided`, or `is_omitted`. It also supports `enum`. Type values are string / number / integer / boolean ([U] on the exact enum names, though these are standard JSON Schema).
- `request_headers` values: a plain string, `{"secret_id": "..."}` (from the agent's secret store), or `{"variable_name": "..."}` (a dynamic variable).
- Auth options: custom header, Bearer via secret header, Basic, OAuth2 client credentials, OAuth2 JWT.
- Other tool fields: `response_timeout_secs` (webhook range 5-300, default 20), `execution_mode` (`immediate` | `post_tool_speech` | `async`), `pre_tool_speech` (`auto` | `force` | `off`), `tool_call_sound` (`typing`, `elevator1-4`), `interruption_mode`, `tool_error_handling_mode` (`auto` | `summarized` | `passthrough` | `hide`), `assignments` (copies response fields into dynamic variables, e.g. `{"dynamic_variable":"ticket_id","value_path":"ticket_id","source":"response"}`).
- To attach tools to an agent, put the tool IDs in `conversation_config.agent.prompt.tool_ids`.
- Recommended LLMs for tool calling: "GPT 5.2, Gemini-2.5-Flash, or Claude Sonnet 4.5". Avoid Gemini-2.0-Flash.
- ElevenLabs egress IPs, if we want to allowlist (US: 34.67.146.145, 34.59.11.47): https://elevenlabs.io/docs/eleven-api/resources/ip-allowlisting [V]

### Example: `create_ticket` → `POST /tickets`

```json
{
  "tool_config": {
    "type": "webhook",
    "name": "create_ticket",
    "description": "Creates a City of Calgary 311 snow/ice service request. Call ONLY after you have read the details back to the caller and they confirmed. Requires a location: either latitude+longitude or a street intersection.",
    "response_timeout_secs": 15,
    "pre_tool_speech": "force",
    "tool_call_sound": "typing",
    "api_schema": {
      "url": "https://<your-ngrok-or-host>/tickets",
      "method": "POST",
      "content_type": "application/json",
      "request_headers": {
        "X-CivicSignal-Key": { "secret_id": "<secret id from agent secrets>" }
      },
      "request_body_schema": {
        "type": "object",
        "description": "311 ticket payload",
        "required": ["service_name", "description"],
        "properties": {
          "service_name": {
            "type": "string",
            "description": "Service category for the request.",
            "enum": ["Snow and Ice - Sidewalk", "Snow and Ice - Road", "Snow and Ice - Transit Stop", "Snow and Ice - Pathway"]
          },
          "latitude": {
            "type": "number",
            "description": "Decimal latitude in Calgary (about 50.8 to 51.2) if the caller gives an address or landmark you can geocode confidently; otherwise omit."
          },
          "longitude": {
            "type": "number",
            "description": "Decimal longitude in Calgary (about -114.3 to -113.8); omit if unknown."
          },
          "intersection": {
            "type": "string",
            "description": "Nearest intersection in the form 'Street A & Street B', e.g. '17 Ave SW & 14 St SW'. Always include the quadrant (NW/NE/SW/SE)."
          },
          "description": {
            "type": "string",
            "description": "One or two English sentences summarizing the problem, translated to English if the caller spoke another language."
          },
          "hazard_notes": {
            "type": "string",
            "description": "Safety-relevant details: ice under snow, mobility-impaired resident, school zone, hill, blocked hydrant. Empty string if none."
          },
          "caller_language": {
            "type": "string",
            "dynamic_variable": "system__language"
          }
        }
      }
    },
    "assignments": [
      { "dynamic_variable": "ticket_id", "value_path": "ticket_id", "source": "response" }
    ]
  }
}
```
[U] `system__language` as a system dynamic variable name is a guess. Remove that property if it errors, or use a `description` instead. Enum values above are placeholders; match them to the backend. Marking `enum` on `service_name` is supported per the API ref.

### Example: `report_disruption` → `POST /disruption`

```json
{
  "tool_config": {
    "type": "webhook",
    "name": "report_disruption",
    "description": "Dispatcher-only: records the current crew availability and whether a demand surge is underway. Use when a dispatcher states how many crews are out or declares a surge.",
    "response_timeout_secs": 10,
    "api_schema": {
      "url": "https://<your-ngrok-or-host>/disruption",
      "method": "POST",
      "request_headers": { "X-CivicSignal-Key": { "secret_id": "<secret id>" } },
      "request_body_schema": {
        "type": "object",
        "required": ["crews_out", "surge"],
        "properties": {
          "crews_out": { "type": "integer", "description": "Number of plow/sanding crews currently unavailable (integer >= 0)." },
          "surge": { "type": "boolean", "description": "true if the dispatcher says call volume is surging / storm event declared, otherwise false." }
        }
      }
    }
  }
}
```
Python creation pattern (from the docs):
```python
from elevenlabs import ElevenLabs, ToolRequestModel
el = ElevenLabs()  # reads ELEVENLABS_API_KEY
tool = el.conversational_ai.tools.create(request=ToolRequestModel(tool_config={...}))
el.conversational_ai.agents.update(agent_id=AGENT_ID,
    conversation_config={"agent": {"prompt": {"tool_ids": [tool.id]}}})
```
Recommendation: put `report_disruption` on a **separate dispatcher agent** (the docs advise "Keep agents specialized": https://elevenlabs.io/docs/eleven-agents/best-practices/prompting-guide).

The CLI alternative is `elevenlabs tools add "create_ticket" --type webhook --config-path ./tool_configs/create_ticket.json`, then `elevenlabs agents push` (webhook tools doc).

---

## 2. System prompt and guardrails

Prompting guide: https://elevenlabs.io/docs/eleven-agents/best-practices/prompting-guide
Guardrails: https://elevenlabs.io/docs/eleven-agents/best-practices/guardrails

[V] Best practices from the docs:
- Split the prompt into markdown sections: `# Personality`, `# Goal`, `# Guardrails`, `# Tone`, `# Tools`, `# Tool error handling`. "Models are tuned to pay extra attention to certain headings (especially `# Guardrails`)."
- Mark critical lines with "This step is important." Repeat the 1-2 most critical rules twice.
- Be concise. Put format expectations in parameter descriptions. For each tool, state when to use it, how to use it, and how to handle errors.
- Tool failure handling: acknowledge the problem, never invent data, retry once, then escalate.
- Text normalization: the default is `system_prompt`, where the LLM writes numbers out as words. Alternatively, `text_normalisation_type: "elevenlabs"` keeps transcripts clean at the cost of a little latency. That's relevant for ticket numbers and addresses.
- Platform guardrails (Guardrails 2.0): **Focus** (keeps the agent on topic, GA, free), **Manipulation** (blocks prompt injection, GA, free, ends the call), **Content** (alpha, free), **Custom** (alpha, LLM-billed, natural-language rule). Voice agents should use `streaming` mode. Exit strategy is `end_call` or `retry`, and retry needs blocking mode. Retry feedback can call `transfer_to_number`.
- System tools: `end_call`, `language_detection`, `transfer_to_number`, `transfer_to_agent`, `skip_turn` (https://elevenlabs.io/docs/eleven-agents/customization/tools/system-tools).

Draft prompt skeleton (our own content, not from the docs):
```
# Personality
You are CivicSignal, the City of Calgary 311 voice assistant for snow and ice issues. Calm, brief, plain language.

# Goal
1. Determine the problem and location (intersection with quadrant, or address).
2. Ask about hazards (ice, mobility needs, school zone, hills).
3. Read back: "I have <problem> at <location>, hazards: <x>. Is that correct?" Wait for a yes. This step is important.
4. Only after confirmation, call create_ticket. Then tell the caller the ticket number digit by digit.

# Guardrails
If anyone is injured, trapped, in a vehicle collision, or in immediate danger, tell them to hang up and call 911 now, and do not create a ticket first. This step is important.
Never promise a time when a crew will arrive.
Only discuss Calgary snow/ice 311 matters; politely redirect anything else to 311 or calgary.ca.
Never call create_ticket without an explicit caller confirmation of the read-back. This step is important.

# Language
Reply in the caller's language. Always write ticket description in English.

# Tool error handling
If create_ticket fails, apologize, retry once, then give the caller 311 as a fallback. Never invent a ticket number.
```

---

## 3. Languages

Docs: https://elevenlabs.io/docs/eleven-agents/customization/voice/customization/language
Language detection: https://elevenlabs.io/docs/eleven-agents/customization/tools/system-tools/language-detection
Models: https://elevenlabs.io/docs/overview/models | FAQ: https://elevenlabs.io/docs/help-center/other/what-languages-do-you-support.md

[V] **One agent can be multilingual.** You set a primary `conversation_config.agent.language` plus `conversation_config.language_presets` for each extra language. Each preset can override the first message and the voice.
[V] **Automatic switching works through the `language_detection` system tool.** It is NOT on by default. It switches when the user speaks another language or asks to switch. Target languages must already be listed in the agent's Additional Languages. Optional `only_at_conversation_start` limits switching to the first 2 user turns. Recommendation from the docs: "enable all languages for an agent and enabling the language detection system tool."
[V] Without that tool, the widget asks the user to pick a language before the call. The language page also says "Language selection is fixed for the duration of the call". That conflicts with the detection tool doc, which allows mid-call switches. **[U]** Expect the tool to handle switching; test it.
[V] The language page says choosing "All" adds **31 languages**. That number matches the Flash v2.5 list, which suggests this page is stale relative to v3 Conversational. **[U]**
[V] Help center: "All the languages supported by our v3 Conversational and Flash v2.5 models can be used with ElevenAgents." (https://elevenlabs.io/docs/help-center/product/eleven-agents/which-languages-can-i-use-with-eleven-agents.md)
[V] **Eleven v3 Conversational** (`eleven_v3_conversational`, about 280 ms) supports 70+ languages and is "priced the same as other ElevenLabs TTS models in Agents". Select it in Agent Voice tab → TTS model (https://elevenlabs.io/docs/eleven-agents/customization/voice/expressive-mode). The same page's config example uses `"model_id": "eleven_v4_turbo"`, so v4 Turbo appears selectable for agents too **[U]**.

| Language | TTS: Flash v2.5 (32) | TTS: v3 / v3 Conversational (74) | TTS: v4 / v4 Turbo (90+) | STT (Scribe v2 WER tier) |
|---|---|---|---|---|
| Spanish | yes | yes | yes | Excellent ≤5% |
| French | yes | yes | yes | Excellent ≤5% |
| Mandarin | yes (`zh`) | yes (cmn) | yes | High 5-10% |
| Arabic | yes | yes | yes | Good 10-20% |
| Tagalog/Filipino | yes (`fil`) | yes | yes | High 5-10% |
| Punjabi | **no** | yes (pan) | yes | Good 10-20% |
| Urdu | **no** | yes (urd) | yes | **Moderate 25-50%** (weak) |
| Cantonese | **no** | **no** | **yes (yue)** | High 5-10% |

Sources: TTS columns from https://elevenlabs.io/docs/overview/models and https://elevenlabs.io/docs/help-center/other/what-languages-do-you-support.md. STT column from https://elevenlabs.io/docs/overview/capabilities/speech-to-text (Scribe v2 batch WER table). **[U]** The table doesn't confirm that the agent's real-time ASR has the same accuracy as batch Scribe v2, or that `yue` is a selectable language code in the agent's Additional Languages dropdown. Check the dropdown. **Implication:** for the demo, pick v3 Conversational (or v4 Turbo if Cantonese is needed) and showcase Punjabi, Tagalog, Mandarin, or Spanish. Avoid making Urdu the hero language because ASR accuracy is weak.

---

## 4. Creator tier: credits, minutes, concurrency, sharing

- Plans [V] (https://elevenlabs.io/pricing): Free $0 / 10k credits, Starter $6 / 30k, **Creator $22 / 121,000 credits ($11 first month)**, Pro $99 / 600k.
- Agents [V] (https://elevenlabs.io/pricing/agents): Free 15 min / 4 concurrent, Starter 75 / 6, **Creator 275 min / 10 concurrent**, Pro 1,238 / 20, Scale 3,738 / 30, Business 12,375 / 40. Extra minutes cost $0.08, burst minutes cost $0.16, text messages cost $0.003. LLM costs are extra. "ElevenLabs does not charge extra for telephony" (Twilio charges its own fees).
- **Credits per minute:** the page says agents are "billed by call minutes, not by the shared credit pool". 121,000 / 275 is about 440 credits per minute, but that is my inference, not a published figure **[U]**. Older docs/blogs cite different rates, so don't rely on them.
- **Concurrency on Creator: 10**, and with burst enabled 30 at 2x price, with lower ASR/TTS priority [V] (https://elevenlabs.io/docs/eleven-agents/guides/burst-pricing). Burst is enabled per agent: Security tab → Limits → "Enable bursting", or `platform_settings.call_limits.bursting_enabled: true`. Calls over the cap are rejected unless call queueing is on (https://elevenlabs.io/docs/eleven-agents/guides/call-queueing).
- **Number of agents is unlimited on every plan**. You're limited only by concurrency and the monthly limit [V] (pricing/agents FAQ).
- **Public link / widget** [V] (https://elevenlabs.io/docs/eleven-agents/customization/widget):
  ```html
  <elevenlabs-convai agent-id="agent_xxx"></elevenlabs-convai>
  <script src="https://unpkg.com/@elevenlabs/convai-widget-embed" async type="text/javascript"></script>
  ```
  "Widgets currently require public agents with authentication disabled" (Advanced tab). There is a customizable **"Shareable page"**, a public widget landing page, which is ideal as a QR target. **[U]** The exact URL format is roughly `https://elevenlabs.io/app/talk-to?agent_id=...`; copy it from the dashboard. A widget `language="es"` attribute presets the language. Use the Security tab's Allowlist to restrict the embedding domains.
- Python SDK for a public agent doesn't need an API key (https://elevenlabs.io/docs/eleven-agents/libraries/python).

---

## 5. Phone

### Twilio native integration [V] (https://elevenlabs.io/docs/eleven-agents/phone-numbers/twilio-integration/native-integration)
1. Buy a Twilio number. Inbound calls need a **purchased** number; verified caller IDs only support outbound.
2. ElevenAgents dashboard → **Phone Numbers** → Import: label, number, Twilio Account SID + Auth Token (or API Key SID `SK...` + secret, which is recommended).
3. ElevenLabs auto-configures the Twilio number's webhooks.
4. Assign the agent to the number. Call to test, then check Calls History.
Also available: SMS conversations, Twilio personalization webhook (an inbound call fetches dynamic variables like the caller number), and register-call (bring your own Twilio TwiML).

### SIP trunk [V] (https://elevenlabs.io/docs/eleven-agents/phone-numbers/sip-trunking)
- ElevenLabs endpoints: `sip:<E164-number>@sip.rtc.elevenlabs.io:5060;transport=tcp`, `:5061;transport=tls`, or UDP on 5060, which is experimental and for testing only. The identifier/number is required in the URI.
- Codecs: G.711 (PCMU/PCMA) or G.722.
- Dashboard → Phone Numbers → Import SIP Trunk: E.164 number, inbound settings (allowed source IPs (TCP/TLS only), remote domains, optional digest auth), outbound settings (address, transport, media encryption, codecs, digest auth). Then assign the agent.
- Custom SIP headers can map to dynamic variables.
- Provider guides cover Telnyx, Plivo, Bandwidth, Sinch, and Vonage.

### Twilio trial limits (inbound) [V] (https://static1.twilio.com/docs/usage/trials/try-out-voice; https://support.twilio.com/hc/en-us/articles/360036052753)
- Trial accounts can **only make or receive calls from verified numbers**, with up to 5 verified numbers. **A random audience member cannot call a trial number.**
- A trial message plays before your TwiML and asks the caller to press a key. That will sit in front of the agent greeting.
- 10-minute limit per call, 75 minutes total voice quota, max 5 concurrent calls.
- Fix: upgrade Twilio (pay-as-you-go, about $20 top-up **[U]** amount) before any public phone demo. **[U]** Canadian (403/587/825) local numbers may need regulatory bundle/address info in Twilio, so allow lead time. Otherwise use the web widget/QR for the audience and keep the phone path for a single verified-phone demo.

---

## 6. TTS API for crew briefings (Python)

- Package: **`elevenlabs`** (`pip install elevenlabs`) [V] (https://elevenlabs.io/docs/eleven-api/quickstart).
- Endpoint: `POST https://api.elevenlabs.io/v1/text-to-speech/{voice_id}`, header `xi-api-key`, body `{"text", "model_id"}`, query `output_format` (default `mp3_44100_128`). The default model if omitted is `eleven_multilingual_v2` [V] (https://elevenlabs.io/docs/api-reference/text-to-speech/convert). There's also a `/stream` variant [U, standard].
- Model IDs [V] (https://elevenlabs.io/docs/overview/models):
  - `eleven_flash_v2_5`: about 75 ms, 32 languages, cheapest. **Latency-optimized pick for English/French/Spanish/Mandarin/Filipino briefings.**
  - `eleven_flash_v2`: English-only, about 75 ms.
  - `eleven_v4_turbo`: about 100 ms, 90+ languages, most expressive real-time option.
  - `eleven_v4`: highest quality, 90+ languages. The quickstart now uses this.
  - `eleven_multilingual_v2`: 29 languages, higher latency.
  - `eleven_turbo_v2_5` is deprecated in favor of `eleven_flash_v2_5`.
  - `optimize_streaming_latency` param is deprecated.
- Minimal code (adapted from the quickstart):
```python
import os
from elevenlabs.client import ElevenLabs

el = ElevenLabs(api_key=os.environ["ELEVENLABS_API_KEY"])
audio = el.text_to_speech.convert(
    voice_id="JBFqnCBsd6RMkjVDRZzb",          # "George"
    text="Crew 4: priority sidewalk, 17 Ave and 14 St SW. Ice under snow, school zone.",
    model_id="eleven_flash_v2_5",
    output_format="mp3_44100_128",
)
with open("briefing.mp3", "wb") as f:
    for chunk in audio:   # convert returns an iterator of bytes
        f.write(chunk)
```
(The quickstart uses `elevenlabs.play.play(audio)`, which needs mpv/ffmpeg. Writing chunks to a file is the standard SDK pattern **[U]** for the iterator detail.)
- TTS credits come out of the 121k credit pool. Flash models cost fewer credits per character than v4/multilingual **[U]** on the exact ratio.

---

## 7. Testing webhooks locally

- ElevenLabs calls your tool URL from its cloud, so `localhost` won't work. You need a public HTTPS URL. The ElevenLabs docs use **ngrok** ("use ngrok, or a similar service, to create a public URL", Vonage guide: https://elevenlabs.io/docs/agents-platform/phone-numbers/telephony/vonage). I found no ElevenLabs-specific tunneling product. Cloudflare Tunnel (`cloudflared tunnel --url http://localhost:8000`) works equally well **[U, not in EL docs]**.
  - `ngrok http 8000`, then put `https://<id>.ngrok-free.app/tickets` in the tool URL. Free-tier ngrok URLs change on every restart, so update the tool via the API/CLI. **[U]** ngrok free shows a browser interstitial, which does not affect server-to-server POSTs.
- Built-in testing [V] (https://elevenlabs.io/docs/eleven-agents/customization/agent-testing): simulation tests with **tool mocking** (mock all / selected / none, with fallback to the real tool). This works before the backend is live.
- Post-call webhooks (an optional conversation transcript push) are HMAC-signed with the `ElevenLabs-Signature` header. Verify them with the Python SDK's `construct_event(rawBody, sig_header, secret)` [V] (https://elevenlabs.io/docs/eleven-agents/workflows/post-call-webhooks).
- For FastAPI, verify a shared-secret header (the `X-CivicSignal-Key` secret above) on `/tickets` and `/disruption`. Optionally allowlist ElevenLabs egress IPs.

---

## Unverified / to check in the dashboard
1. Credits per agent minute on Creator (inferred about 440; the page says minutes are not billed from the credit pool).
2. Whether burst/overage works on Creator without Pay-As-You-Go credits enabled.
3. Whether Cantonese (`yue`) is selectable as an agent language (it requires v4-family TTS).
4. The exact shareable-page URL format.
5. Whether real-time agent ASR accuracy matches the Scribe v2 batch WER table, especially Urdu (moderate) and Punjabi (good).
6. Exact names of system dynamic variables (e.g. language, caller ID).
7. Twilio upgrade minimum and Canadian number regulatory requirements.
