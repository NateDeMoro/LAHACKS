"""Register each running local agent with Agentverse as a mailbox agent (what the inspector's Connect does).
Needs the agents running and AGENTVERSE_KEY in .env. Run: uv run --group agent --env-file .env python scripts/connect_agents.py"""
import os
import sys

import httpx

AGENTS = {"waiting-room-triage": 8001, "rider-intake": 8002, "rider-evidence": 8003}


def main() -> int:
    key = os.environ.get("AGENTVERSE_KEY")
    if not key:
        print("AGENTVERSE_KEY is not set")
        return 1
    bad = 0
    for name, port in AGENTS.items():
        try:
            r = httpx.post(f"http://127.0.0.1:{port}/connect", json={"user_token": key, "agent_type": "mailbox"}, timeout=30)
            ok = r.status_code == 200 and r.json().get("success")
        except httpx.HTTPError as e:
            ok, r = False, e
        print(f"{name} (:{port}): {'connected' if ok else f'FAILED {r}'}")
        bad += not ok
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
