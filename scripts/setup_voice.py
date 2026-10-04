"""Create or update the SnowTech ElevenLabs agents and their webhook tools.

Usage:
    .venv/bin/python scripts/setup_voice.py https://<tunnel-host>

The prompts and tool configs are read from voice/agent.md (single source of truth).
Re-running with a new tunnel URL updates the existing tools in place. IDs are kept in
voice/agents.json. Needs ELEVENLABS_API_KEY and CIVICSIGNAL_KEY in .env.
"""
import json
import re
import sys
from pathlib import Path

import requests

ROOT = Path(__file__).resolve().parent.parent
SPEC = ROOT / "voice" / "agent.md"
STATE = ROOT / "voice" / "agents.json"
API = "https://api.elevenlabs.io/v1/convai"

DISPATCH_FIRST = "SnowTech dispatch. What changed on the ground?"


def load_env():
    env = {}
    for line in (ROOT / ".env").read_text().splitlines():
        if "=" in line and not line.startswith("#"):
            k, v = line.split("=", 1)
            env[k.strip()] = v.strip()
    return env


def parse_spec():
    """Return the two prompts, two tool configs and the intake first message from agent.md."""
    text = SPEC.read_text()
    sections = re.split(r"^## ", text, flags=re.M)
    by_num = {s[:1]: s for s in sections if s[:1].isdigit()}
    block = lambda s, lang="": re.search(rf"```{lang}\n(.*?)```", s, re.S).group(1).strip()
    first = re.search(r'First message: "(.*?)"', by_num["1"]).group(1)
    return {
        "intake_prompt": block(by_num["1"]),
        "intake_first": first,
        "create_ticket": json.loads(block(by_num["2"], "json"))["tool_config"],
        "dispatch_prompt": block(by_num["3"]),
        "report_disruption": json.loads(block(by_num["4"], "json"))["tool_config"],
    }


class Client:
    def __init__(self, key):
        self.s = requests.Session()
        self.s.headers["xi-api-key"] = key

    def call(self, method, path, body=None):
        r = self.s.request(method, f"{API}{path}", json=body, timeout=30)
        if not r.ok:
            sys.exit(f"{method} {path} -> {r.status_code}: {r.text[:800]}")
        return r.json() if r.content else {}


def wire_tool(cfg, base_url, secret_id, path):
    cfg = json.loads(json.dumps(cfg))
    cfg["api_schema"]["url"] = base_url.rstrip("/") + path
    cfg["api_schema"]["request_headers"] = {"X-CivicSignal-Key": {"secret_id": secret_id}}
    return cfg


# System tool so the agent can actually hang up; without it the prompt's "end the call"
# step makes the agent offer to end the call but it cannot.
END_CALL = {
    "type": "system",
    "name": "end_call",
    "description": "End the call after the caller confirms they have nothing else to report, "
                   "or after telling them to call 9-1-1.",
    "params": {"system_tool_type": "end_call"},
}

# Lets the agent stay silent when the caller asks for a moment. Without it the 7 s turn
# timeout forced a re-prompt every ~10 s ("I'm still here...") while the caller waited.
SKIP_TURN = {
    "type": "system",
    "name": "skip_turn",
    "description": "Stay silent and wait when the caller asks for a moment (\"give me a second\", "
                   "\"hold on\", \"let me check\"). Resume only when they speak.",
    "params": {"system_tool_type": "skip_turn"},
}

# Seconds of caller silence before the agent speaks again (was the 7 s default).
TURN_TIMEOUT_S = 20


def agent_body(name, prompt, first, tool_ids):
    return {
        "name": name,
        "conversation_config": {
            "agent": {
                "first_message": first,
                "language": "en",
                "prompt": {"prompt": prompt, "tool_ids": tool_ids,
                           "built_in_tools": {"end_call": END_CALL, "skip_turn": SKIP_TURN}},
            },
            "turn": {"turn_timeout": TURN_TIMEOUT_S},
        },
    }


def main():
    if len(sys.argv) != 2 or not sys.argv[1].startswith("https://"):
        sys.exit(__doc__)
    base = sys.argv[1]
    env = load_env()
    spec = parse_spec()
    c = Client(env["ELEVENLABS_API_KEY"])
    state = json.loads(STATE.read_text()) if STATE.exists() else {}

    if "secret_id" not in state:
        res = c.call("POST", "/secrets", {"type": "new", "name": "civicsignal_key",
                                          "value": env["CIVICSIGNAL_KEY"]})
        state["secret_id"] = res["secret_id"]

    for name, path in [("create_ticket", "/tickets"), ("report_disruption", "/disruption")]:
        cfg = wire_tool(spec[name], base, state["secret_id"], path)
        if name in state.get("tools", {}):
            c.call("PATCH", f"/tools/{state['tools'][name]}", {"tool_config": cfg})
        else:
            state.setdefault("tools", {})[name] = c.call("POST", "/tools", {"tool_config": cfg})["id"]

    agents = {
        "intake": ("SnowTech 311 intake", spec["intake_prompt"], spec["intake_first"],
                   [state["tools"]["create_ticket"]]),
        "dispatcher": ("SnowTech dispatcher", spec["dispatch_prompt"], DISPATCH_FIRST,
                       [state["tools"]["report_disruption"]]),
    }
    for key, args in agents.items():
        body = agent_body(*args)
        if key in state.get("agents", {}):
            c.call("PATCH", f"/agents/{state['agents'][key]}", body)
        else:
            state.setdefault("agents", {})[key] = c.call("POST", "/agents/create", body)["agent_id"]

    state["base_url"] = base
    STATE.write_text(json.dumps(state, indent=2) + "\n")
    for key, aid in state["agents"].items():
        print(f"{key}: https://elevenlabs.io/app/talk-to?agent_id={aid}")


if __name__ == "__main__":
    main()
