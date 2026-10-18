# Rider Triage Agent (waiting room)

![tag:innovationlab](https://img.shields.io/badge/innovationlab-3D8BD3) ![tag:hackathon](https://img.shields.io/badge/hackathon-5F43F1)

Agent name: `rider-triage`
Address: `agent1q0gpg656yj08w8ssyy8d3lwnygthzhmszpe3wwxwr2dystersw8fgxl3xf8`

## What it does
A triage assistant for an ER waiting room monitored by wearable sensors, driven entirely from ASI:One chat. A nurse can:
- ask who needs a recheck (open alerts and latest risk level, read live from the monitoring backend), and
- add a new patient by typing, including any medical condition. The condition is looked up in the NLM Clinical Tables vocabulary, so an invented name is rejected. For a real condition with no table rule, PubMed abstracts are searched and the model may pick a limit **only from a preset menu** (it never writes a number); code checks keep the pick only if two real abstracts quote it. The result is a **warning-level** limit for that one patient, labeled unreviewed, with sources listed. The nurse stays the decision-maker.

Example prompts:
- "Who needs a recheck right now?"
- "Add a 67 year old man with sepsis, cough and fever since yesterday. What changed for him?"
- "Add a 55 year old woman with pulmonary embolism."

## Agents (all registered on Agentverse, all use messages between agents)
| Agent | Role |
|---|---|
| `rider-triage` (this one) | The only agent users talk to. Chat Protocol with ASI:One tool calling. Reads the board and starts intakes through the backend. |
| `rider-intake` | Applies the reviewed table rules to an intake and looks up typed conditions. Asks the evidence agent for a draft for each real condition, in parallel. |
| `rider-evidence` | Searches PubMed for one condition and drafts a cited, warning-only limit from the preset menu, or abstains. |

The backend (risk engine, dashboard) sends its adjuster and condition work to the intake agent over agent messages and falls back to running it in-process if an agent does not answer.

## Monetization approach
Per-clinic subscription for the monitoring dashboard, with the agent as an included query channel (a charge-nurse could ask it from any ASI:One-connected device). Optional per-query pricing for third-party agents (for example a bed-management agent) that call it.

## Setup and run
1. `cp .env.example .env`; set `FETCHAI_API_KEY` (ASI:One key), `AGENTVERSE_KEY` (Agentverse API key), `AGENT_SEED` (any fixed secret phrase; keeps the addresses stable) and the StepFun key.
2. Start the backend with agents on: `USE_AGENTS=1 uv run --group agent --env-file .env uvicorn backend.app:create_app --factory --port 8000` (omit `USE_AGENTS` to run everything in-process).
3. Start the three agents: `./scripts/run_agents.sh` (ports 8001-8003, logs in `logs/agents/`).
4. Register them as mailbox agents: `uv run --group agent --env-file .env python scripts/connect_agents.py`.
5. ASI:One test: in asi1.ai enable Agents, find `rider-triage`, and ask one of the example prompts.
6. Keep the backend and the agents running during any test; a mailbox only delivers while the agent process is up.

## Devpost deliverables
ASI:One chat session URL, Agentverse agent URL, public repo, 3-5 minute video.
