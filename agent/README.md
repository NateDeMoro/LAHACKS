# Waiting-Room Triage Agent

![tag:innovationlab](https://img.shields.io/badge/innovationlab-3D8BD3) ![tag:hackathon](https://img.shields.io/badge/hackathon-5F43F1)

Agent name: `waiting-room-triage`
Address: `agent1q...` (fill in from the agent's startup log)

## What it does
Answers a triage nurse's questions about the ER waiting room, live. It reads our monitoring backend (read-only): which waiting patients have open alerts, and each patient's latest risk result (NEWS2, per-vital levels, trend tier). Alerts replaced by a newer alert and patients already called in are left out. ASI:One does the reasoning through function calling. Uses the Agent Chat Protocol.

Example question: "Who needs a recheck right now?"

## Monetization approach
Per-clinic subscription for the monitoring dashboard, with the agent as an included query channel (a charge-nurse could ask it from any ASI:One-connected device). Optional per-query pricing for third-party agents (for example a bed-management agent) that call it.

## Setup and run
1. `cp .env.example .env`; set `FETCHAI_API_KEY` (ASI:One key), `AGENT_SEED` (any fixed phrase, keeps the address stable).
2. Start the backend: `uv run uvicorn backend.app:create_app --factory --port 8000` (and play the scenario so there is data).
3. Start the agent: `uv run --group agent --env-file .env python -m agent.main` (port 8001).
4. Mailbox: open the "Agent inspector" link printed in the log, click Connect, choose Mailbox, finish. The "mailbox not found" warning goes away.
5. Agentverse: open the agent under Local Agents, set its name and paste this README into its README tab. Confirm the badges show.
6. ASI:One test: in asi1.ai, enable Agents, find the agent by name or address, ask the example question. The answer should match the board.
7. Keep backend and agent running on the laptop during any test.

## Devpost deliverables
ASI:One chat session URL, Agentverse agent URL, public repo, 3-5 minute video.
