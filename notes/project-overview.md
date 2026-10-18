# Waiting Room Vitals Monitor: Project Overview

Oct 17, 2026 · @Nate

A chest strap and a risk engine that tell ER and urgent-care triage nurses which waiting patient to recheck next. It tightens the alert thresholds using each patient's intake information and catches patients trending toward danger before a manual recheck would. It is decision support, not a diagnosis, built as a research prototype.

Where to look next:

| Doc | What it holds |
| --- | --- |
| [component-map.md](component-map.md) | Components, owners, interface contracts I1–I15. The source of truth for anything passed between components |
| [build-order.md](build-order.md) | Parallel lanes, step dependencies, checkpoints C1–C4 |
| [stack-reference.md](stack-reference.md) | Libraries and tools per component |
| [simulation-layer.md](simulation-layer.md) | Sample patients, run scripts, trend pre-roll, end of run |
| [risk-model-training-plan.md](risk-model-training-plan.md) | Datasets, methods and evaluation for every part of the risk engine |

## Why it matters

- Sepsis: about 1.7M US adults a year, at least 350,000 deaths; most cases start before the hospital (CDC).
- Each hour of antibiotic delay raises the odds of death: OR 1.04 per hour (Seymour 2017), 1.09 per hour (Liu).
- Continuous monitoring in an ED caught deterioration a median of 65 minutes earlier than manual checks in a subgroup of 31 patients (SNAP40-ED). SAFE-WAIT (Western Sydney) is a related waiting-room precedent.

## Demo

- **One patient: the wearer, in two modes.** Live mode: the Polar H10 strap supplies real heart rate and breathing rate and the simulator fills in SpO2 and temperature, shown alongside the real values. Run mode: the simulator supplies every vital and the strap is ignored. The data carries no real/simulated tag; we say which is which in the pitch.
- **Sample patients and runs.** Six fictional patients (two healthy, two at risk, two critical) can prefill the intake form. A dashboard button starts that patient's 10-minute run: every vital follows a script, the trend models get two hours of starting-value history first, and at the end the data stops and the screen shows a pause with alerts still up. See [simulation-layer.md](simulation-layer.md).
- **Live feel.** Vitals and NEWS2 update every second on the dashboard; trend models and alerts run every minute.

## Hardware

- **Polar H10 chest strap,** connected over Bluetooth straight to the laptop with the Python `bleakheart` library. No ESP32, no thermistor, no oximeter.
- **Two Bluetooth services:** the standard Heart Rate Service (heart rate, beat intervals in 1/1024 s, sensor-contact flag), about once a second; and Polar's PMD service (ECG at about 130 Hz, accelerometer). We need only the standard one; ECG only if the dashboard gets a live waveform.
- **Polar app off.** Close the Polar phone app while testing so it doesn't hold the strap's connection.
- **One laptop.** The receiver must run on the laptop the strap is paired with; keeping the backend and dashboard there too avoids networking.

## Inputs

### Vitals

The seven NEWS2 parts, plus beat intervals.

| Vital | Source | Cadence |
| --- | --- | --- |
| Heart rate | Strap (real); scripted in a run | About 1/s |
| Beat intervals | Strap (real) | Every beat |
| Breathing rate | Computed in the receiver from beat intervals (respiratory sinus arrhythmia) | About 1/s, over a rolling window |
| SpO2 | Simulated (filler in live mode, scripted in a run) | About 1/s |
| Temperature | Simulated (filler in live mode, scripted in a run) | About 1/s |
| Blood pressure | One reading at triage, never repeated (a sample patient carries it) | Once |
| Alertness | Nurse enters at triage | Once |
| On supplemental oxygen | Intake yes/no | Once |

### Intake profile

Age, sex (male or female; NHANES records only these), height and weight (metric), pregnancy, a conditions checklist, medications, chief complaint (free text), triage set (BP, alertness, pain 0–10, on oxygen, ESI level 1–5), arrival time. Fields and values are in I2.

- **Conditions:** every condition with enough NHANES participants to fit a shift (counts in the training plan): hypertension, asthma, cancer, diabetes, thyroid, COPD, liver, heart disease (coronary, angina, heart attack combined), stroke, heart failure. Kidney disease pending a check.
- **Medications:** names as typed, mapped to drug classes with NHANES RXQ_DRUG.
- **Left out on purpose:** known resting heart rate and athlete status, which a real intake form wouldn't have.

## How the risk engine works

Plain-English version; methods and data are in the training plan.

1. **Baseline ranges (at intake).** Each vital gets three bands. Safe comes from an NHANES quantile fit on the patient's profile, i.e. where 95% of similar people sit. Danger starts at the NEWS2 score-3 values. Warning is everything in between.
2. **Context adjuster (at intake).** step-5-preview reads the full profile and chief complaint and proposes tightened danger thresholds from an allowed rule list (rules decided later). A high edge can only move down and a low edge only up, so danger is reached sooner, never later. A code validator approves each change. The fact and exact quote behind each change go to an evaluation log, not to the risk engine. No red flags: triage acuity stays with the nurse's ESI level.
3. **Personal baseline (every minute).** It learns the wearer's own normal from their first stretch of clean readings and narrows the safe band toward it. A drift that stays inside the population range still shows up. It never widens a band, never moves danger, and learns nothing if the patient arrives already abnormal.
4. **NEWS2 (every second).** Scored on the median of the last 60 seconds of each vital. Each part gets 0–3 points and the total runs 0–20. A total of 5 or more is urgent and 7 or more is high. NEWS2 alone treats everyone the same and looks only at now; steps 1–3 personalize it, and step 5 looks ahead. It was validated mainly on admitted patients, which is an assumption we state.
5. **Fast trend model (every minute).** After 15 clean minutes, and only while no vital is in danger: will a vital enter the danger range within 15 minutes? Trained on MIMIC-III minute data. It raises a warning only, never lowers a level, and gives a one-line reason. There is no slow sepsis model (dropped, see decisions.md); sepsis is one cause of deterioration that NEWS2, personal ranges and this model catch.
6. **Alert logic (every minute).** Persistence windows, one alert per problem, worsening supersedes the old alert, alerts stay on the dashboard until a nurse acknowledges them.

## Company challenges

Main track: Applied Intelligence.

| Challenge | What it takes | Where | Effort |
| --- | --- | --- | --- |
| StepFun | The app calls step-5-preview at runtime | Context adjuster | Easy |
| Tiger Data | Readings in TimescaleDB; continuous aggregates can compute the minute medians | Ingest / storage | Easy |
| Sentry | At least two products beyond error monitoring: tracing and logs (session replay on the dashboard as a third) | Whole backend | Easy |
| GoDaddy | Register a domain | Dashboard | Easy |
| Cognition | Build part of the project with Devin | Build process | Easy entry, unlikely win |
| Vultr | Host the backend and dashboard; the laptop posts strap data up | Hosting | Easy, after the laptop version works |
| Fetch.ai | Agent on Agentverse with the Agent Chat Protocol, used entirely inside ASI:One with real tool use | Fetch.ai agent | Medium |
| veri.studio | Fine-tune the context adjuster and show before vs after on the test set | Context adjuster | Medium, if time |

Not targeted:
- **Espressif:** no ESP32. An ESP32 Bluetooth-to-Wi-Fi bridge would win it back.
- **Even Realities:** Even Hub doesn't allow medical, financial or emergency-routing apps.
- **Photon and ElevenLabs:** alerts are dashboard only; no text or voice channel.
- **Base44:** the project must be built on their platform.
- Intuit, Visa, Workday, QNX, Solana, Snowflake: no fit.

## Open decisions

- Context adjuster rule list (I5).
