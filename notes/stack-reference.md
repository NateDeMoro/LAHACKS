# Tech Stack Reference

Oct 17, 2026 · @Nate

One page on what each component is built with. Laptop-only deployment for now because the strap needs Bluetooth on the same machine. Interface IDs (I1–I15) refer to [component-map.md](component-map.md).
These are just leans. Updates can be made as needed, but this doc should be updated with those changes.

## Stack

| Component | Choice | Notes |
| --- | --- | --- |
| Receiver | Python, `bleakheart`, WebSocket client | Runs on the laptop as its own process; computes breathing rate from beat intervals; sends I1 readings to the backend |
| Simulator | Python, asyncio task inside the backend (`backend/simulator/`) | Six sample patients with fixed-length runs started from the dashboard (I12); in a run it supplies every vital and ingest drops the strap; live mode fills SpO2 and temperature; calls the same ingest entry function as the strap, in-process |
| Backend | FastAPI + uvicorn | pydantic models for the reading and risk result; WebSocket push to the dashboard |
| Storage | SQLite (default) | Tiger Data (TimescaleDB) as an add-on for the challenge, written alongside the main store |
| Risk engine: rules | Plain Python | NEWS2, persistence windows, guideline adjustments, personal baseline |
| Risk engine: ML | LightGBM | Saved as LightGBM model files plus JSON (ranges, rules, config), per I7; models may use vitals the strap can't measure |
| LLM layer | OpenAI Python SDK | `backend/llm.py` holds the JSON-completion helper; model, base URL and key from `.env`; StepFun through its OpenAI-compatible endpoint (`https://api.stepfun.ai/v1`) |
| Agent layer | Plain Python pipeline, wrapped as a Fetch.ai uAgent | Details below |
| Dashboard | React + Vite + Tailwind, native WebSocket | Auto-reconnect; Vite proxy to the backend in dev |
| Intake form | Route inside the React app | Posts to the backend |
| Alerts | Photon text (two-way), ElevenLabs voice, dashboard toast as fallback | No Even G2: Even Hub doesn't allow medical apps |
| Observability | Sentry (Python SDK, FastAPI integration) | Spans around ingest, scoring and LLM calls; keep intake free text out of events |
| Hosting | Laptop | Move to Vultr later only if the receiver can post over HTTPS with a shared token |
| Tooling | Python 3.12, `uv`, one `.env` | 3.12 has wheels for CatBoost, LightGBM, bleak and FastAPI. Settings live in `backend/config.py`, one section per component; `.env` holds keys and machine-specific values (`uv run --env-file .env`). Tests: pytest in `tests/` |

## Design rules

- **Three entry points.** The risk engine is a Python module called at three times: once at intake (build ranges from I4 and I5), every second (NEWS2 on the 60 s window, I13 → I14), and every minute (personal baseline, trend models, risk result, I6 → I9). Rules set the floor; ML models can raise a level, never lower one. A small registry picks the model by config.
- **Training is separate.** A `training/` folder holds scripts run with uv (statsmodels for the quantile fit, LightGBM later), not notebooks; outputs are LightGBM model files and JSON (I7). The backend loads the files at startup and never imports training code.
- **Missing vitals are fine.** Models take missing inputs as NaN (LightGBM handles this); the simulator fills what the strap can't.

## LLM and agent layer

- The OpenAI SDK pointed at StepFun's `base_url` replaces LiteLLM (one endpoint, exact control of `response_format` and `reasoning_effort`; the optional veri.studio comparison only swaps `base_url` and model). Only `backend/llm.py` knows the provider. Always validate output with pydantic and retry once on a bad parse. Run with `uv run --env-file .env ...` so the key loads.
- The agent is a fixed pipeline of LLM steps with code between them: fact extractor, history reader, threshold proposer, reviewer, then a code validator. Each step returns a pydantic object. The Fetch.ai uAgent calls the whole pipeline as one function.
- The agent only proposes tightening changes to the NEWS2 danger thresholds, each with a number, a reason and a quote. Only the code validator can approve a change: allowlisted rules, vitals and edges, per-vital caps, no change without a quote found word-for-word in the chief complaint, and a high edge can only move down and a low edge only up. Approved changes go to the risk engine (I5); reasons and quotes go only to the evaluation log (I15).
- Move to LangGraph only if a real loop or branch is needed.
