# RiskER

A wearable and nurse dashboard that ranks ER waiting-room patients by risk in real time.

[Devpost](https://devpost.com/software/risker) · Built at LA Hacks · Research prototype, not a medical device

## Overview

After triage, waiting-room patients can go a long time without a recheck, and some get worse while they wait. RiskER puts a chest strap on each patient and shows nurses a live board of who to recheck next.

Most monitors use one set of alert thresholds for everyone. RiskER personalizes them:

1. It starts from normal ranges for people of the same age, sex and health conditions.
2. It learns each patient's own baseline while they wait.
3. An LLM reads the intake notes and can tighten a patient's limits, but never loosen them.

On top of that, a forecasting model looks 15 minutes ahead and flags patients who are trending toward danger. Every alert comes with a plain-English reason, such as "SpO2 may reach 90% within 15 min."

## Results

| Component | Evaluation | Result |
|---|---|---|
| 15-minute forecast (LightGBM) | Fresh MIMIC-III patients never used in training | Error 26-54% below a no-change baseline; cautious forecasts calibrated within 1.2 points of the 10% target |
| Forecast as an alarm | 203 fresh patients, shipped cutoff | 87% of danger events flagged in the 20 minutes before onset |
| Alert persistence windows | 1,945 eICU ICU stays | 31% fewer alerts on survivors; still alerted on all 167 non-survivors |
| LLM context adjuster | 70 held-out, hand-labeled intake cases | 69/70 exact; precision 1.00, recall 0.98; 0 attempts to loosen a limit |

All training data is from ICUs, where patients are much sicker than in a waiting room, so absolute alert rates here overstate a waiting room. The full evidence for every choice is in `notes/decisions.md`.

## How it works

1. **Wearable.** A Polar H10 strap streams heart rate and beat-to-beat intervals over Bluetooth. Breathing rate is estimated from those intervals. SpO2 and temperature are simulated.
2. **Ingest.** Merges sensor and simulator data into a 30-second window.
3. **Risk engine.** Scores NEWS2, compares each vital to NHANES-fitted population ranges and the patient's learned baseline, and runs the 15-minute forecast.
4. **Alert logic.** Persistence windows, so one noisy reading does not page anyone.
5. **Context adjuster.** StepFun step-5-preview proposes stricter limits from a fixed rule list. Code drops any change whose quote is not word-for-word in the chief complaint.
6. **Dashboard.** Live board, per-patient vitals charts, and the reason behind each alert.
7. **Fetch.ai agent.** Nurses can ask "Who needs a recheck right now?" on ASI:One. The agent reads the board through read-only tools.

## Tech stack

- **ML and data:** Python, pandas, LightGBM; NHANES, eICU, MIMIC-III
- **Backend:** FastAPI, WebSockets, Pydantic, SQLite, TimescaleDB (Tiger Data), Sentry
- **Frontend:** React, TypeScript, Vite, Tailwind, Recharts
- **LLM and agents:** StepFun, Fetch.ai uAgents, Agentverse, ASI:One
- **Hardware:** Polar H10 over Bluetooth LE

## Getting started

Requires Python 3.12 with [uv](https://docs.astral.sh/uv/), and Node 20.19+. The strap is optional; the simulator runs without it.

```
uv sync
cp .env.example .env          # add STEPFUN_API_KEY; other keys are optional
uv run --env-file .env uvicorn backend.app:create_app --factory
```

In a second terminal, start the dashboard and open the URL Vite prints:

```
cd frontend && npm install && npm run dev
```

Optional:

- **Live strap:** `uv run --env-file .env python -m receiver.main` (close the Polar phone app first).
- **Fetch.ai agents:** see `agent/README.md`.
- **Tests:** `uv run pytest`

## Project structure

| Path | Contents |
|---|---|
| `receiver/` | Bluetooth strap receiver and breathing estimate |
| `backend/` | FastAPI app, ingest, risk engine, alerts, LLM adjuster, simulator |
| `frontend/` | React nurse dashboard |
| `training/` | Offline fitting and tuning on NHANES, eICU and MIMIC-III |
| `models/` | Fitted ranges, settings and forecast model files |
| `agent/` | Fetch.ai agents |
| `notes/` | Design notes, interface contracts and the decision log |

## Team

Nathaniel DeMoro and Peyton Nagle.
