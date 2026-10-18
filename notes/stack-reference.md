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
| Risk engine: ML | LightGBM (15-minute forecasting of each vital's lowest/highest value) | Five cautious quantile models plus a JSON bundle in `models/` (I7), imported lazily at runtime; libomp required on Mac, libgomp on Linux; about 0.5 s to load, about 0.2 ms per prediction. Trained offline on MIMIC-III numerics (`training/`, `wfdb` in the training group). MIMIC download: the PhysioNet server is slow (about 100-250 KB/s, many timeouts) and there is no S3 mirror, so `fetch_mimic_numerics.py` uses parallel workers with retries and is rerun to fill gaps; later batches use `--exclude-dir` to avoid earlier patients |
| LLM layer | OpenAI Python SDK | `backend/llm.py` holds the JSON-completion helper; model, base URL and key from `.env`; StepFun through its OpenAI-compatible endpoint (`https://api.stepfun.ai/v1`) |
| Agent layer | Plain Python pipeline, wrapped as a Fetch.ai uAgent | Details below |
| Dashboard | React + Vite + Tailwind, native WebSocket | Auto-reconnect; Vite proxy to the backend in dev |
| Intake form | Route inside the React app | Posts to the backend |
| Alerts | Nurse dashboard only (alert list plus toast, acknowledged from the dashboard) | No Photon or ElevenLabs; no Even G2: Even Hub doesn't allow medical apps |
| Observability | Sentry (Python SDK, FastAPI integration) | Spans around ingest, scoring and LLM calls; keep intake free text out of events |
| Hosting | Laptop | Move to Vultr later only if the receiver can post over HTTPS with a shared token |
| Tooling | Python 3.12, `uv`, one `.env` | 3.12 has wheels for CatBoost, LightGBM, bleak and FastAPI. Settings live in `backend/config.py`, one section per component; `.env` holds keys and machine-specific values (`uv run --env-file .env`). Tests: pytest in `tests/`. LightGBM needs OpenMP: `brew install libomp` on Mac, `libgomp1` (apt) on Linux; without it the fast model is off and everything else still runs |

## Design rules

- **Three entry points.** The risk engine is a Python module called at three times: once at intake (build ranges from I4 and I5), every second (NEWS2 on the 60 s window, I13 → I14), and every minute (personal baseline, fast trend, risk result, I6 → I9). Rules set the floor; ML models can raise a level, never lower one. A small registry picks the model by config.
- **Training is separate.** A `training/` folder holds scripts run with uv (statsmodels for the quantile fit, LightGBM later), not notebooks; outputs are LightGBM model files and JSON (I7). The backend loads the files at startup and never imports training code.
- **Missing vitals are fine.** Models take missing inputs as NaN (LightGBM handles this); the simulator fills what the strap can't.

## LLM and agent layer

- The OpenAI SDK pointed at StepFun's `base_url` replaces LiteLLM (one endpoint, exact control of `response_format` and `reasoning_effort`; the optional veri.studio comparison only swaps `base_url` and model). Only `backend/llm.py` knows the provider. Always validate output with pydantic and retry once on a bad parse. Run with `uv run --env-file .env ...` so the key loads.
- The adjuster is code rules plus one LLM call (`backend/adjuster/`): age, drug classes and the pregnant flag fire rules in code; one call returns facts and quotes for the free-text rules, never a number. The Fetch.ai uAgent calls `adjust(ctx)` as one function.
- The model never sets a limit. Values come from `models/rules.json`; the code validator drops proposals whose rule is off the text list, whose quote is not in the chief complaint (lowercased, straight quotes, collapsed whitespace), that structured fields already fired, or that are text pregnancy with the flag set. A high edge can only move down and a low edge only up. Results go to the risk engine (I5); facts and quotes go only to the evaluation log (I15). Validated proposals are cached in gitignored `logs/`.
- Move to LangGraph only if a real loop or branch is needed.
