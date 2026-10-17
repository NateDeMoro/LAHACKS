# Tech Stack Reference

Oct 17, 2026 · @Nate

One page on what each component is built with. Laptop-only deployment for now because the strap needs Bluetooth on the same machine.
These are just leans. Updates can be made as needed, but this doc shouhld be updated with those changes.

## Stack

| Component | Choice | Notes |
| --- | --- | --- |
| Receiver | Python, `bleakheart`, HTTP/WebSocket client | Runs on the laptop as its own process; posts step-0 readings to the backend |
| Simulator | Python, asyncio task inside the backend | Start, stop and pick a scenario through backend endpoints; same reading format as the strap |
| Backend | FastAPI + uvicorn | pydantic models for the reading and risk result; WebSocket push to the dashboard |
| Storage | SQLite (default) | Tiger Data (TimescaleDB) as an add-on for the challenge, written alongside the main store |
| Risk engine: rules | Plain Python | NEWS2, persistence windows, guideline adjustments, personal baseline |
| Risk engine: ML | Gradient-boosted models (CatBoost, LightGBM, blends) | Model choice is a later trade study; models may use vitals the strap can't measure |
| LLM layer | LiteLLM | One `llm.py` with a JSON-completion helper; model, base URL and key from `.env`; StepFun through its OpenAI-compatible endpoint |
| Agent layer | Plain Python pipeline, wrapped as a Fetch.ai uAgent | Details below |
| Dashboard | React + Vite + Tailwind, native WebSocket | Auto-reconnect; Vite proxy to the backend in dev |
| Intake form | Route inside the React app | Posts to the backend |
| Alerts | Photon text, Even G2 heads-up, dashboard toast as fallback | Glasses client is a separate script listening to the same WebSocket |
| Observability | Sentry (Python SDK, FastAPI integration) | Spans around ingest, scoring and LLM calls; keep intake free text out of events |
| Hosting | Laptop | Move to Vultr later only if the receiver can post over HTTPS with a shared token |
| Tooling | Python 3.12, `uv`, one `.env` | 3.12 has wheels for CatBoost, LightGBM, bleak and FastAPI |

## Design rules

- **One scoring function.** `score_patient(patient, window) -> RiskResult` fronts everything. Rules set the floor; ML models can raise a level, never lower a danger tier. A small registry picks the model by config.
- **Training is separate.** A `training/` folder holds notebooks and outputs saved as joblib files. The backend loads the files at startup and never imports training code.
- **Missing vitals are fine.** Models take missing inputs as NaN (CatBoost and LightGBM handle this); the simulator fills what the strap can't.

## LLM and agent layer

- LiteLLM is used as long as it stays easy. If StepFun's JSON mode misbehaves, only `llm.py` changes (fallback: the OpenAI client with a `base_url`). Always validate output with pydantic and retry once on a bad parse.
- The agent is a fixed pipeline of LLM steps with code between them: fact extractor, history reader, threshold proposer, reviewer, then a code validator. Each step returns a pydantic object. The Fetch.ai uAgent calls the whole pipeline as one function.
- The agent only proposes additive changes to thresholds, each with a number, a reason and a quote. Only the code validator can approve a change: allowlisted vitals and edges, per-vital caps, no change without a quote, and NEWS2 danger edges never move.
- Move to LangGraph only if a real loop or branch is needed.
