# Waiting Room Vitals Monitor: Architecture and Build Order

Oct 17, 2026 · @Nate

The Polar H10 chest strap connects straight to a laptop over Bluetooth; a simulator supplies every other patient and every vital the strap can't measure, in the same format, so the backend treats real and simulated data identically. We build a crude end-to-end pipeline on fake data first, then swap in the strap and improve each piece.

## Components

&#91;embedded content: components · strap on a laptop, no ESP32\]

Every source writes the same reading format into one ingest point, so swapping fake data for the strap (or adding the optional oximeter) changes nothing downstream. The risk engine and alert logic run every minute; the dashboard refreshes every few seconds.

## Company challenges by component

The current plan hits 5 company challenges (StepFun, Photon, Even Realities, Sentry, Fetch.ai), and 5 more are cheap adds. Espressif is lost while the ESP32 stays out.

| Component | Challenge | What it takes | Plan |
| --- | --- | --- | --- |
| Intake form | StepFun | Context adjuster calls step-5-preview to pull facts and pick allowed adjustments | Current |
| Intake form | veri.studio | Fine-tune a small model for the fact-extraction step | Add-on |
| Ingest + storage | Tiger Data | Store vitals readings and risk results in a Tiger Data (TimescaleDB) time-series table | Add-on |
| Risk engine + alert logic | Fetch.ai | Wrap the risk engine or alert logic as an agent on Agentverse, reachable from ASI:One | Current |
| Nurse dashboard | GoDaddy / Vultr (MLH) | Register a domain; host the backend and dashboard | Add-on |
| Whole backend | Sentry | Tracing and error logs across ingest, risk engine and alerts | Current |

## Step 0: data formats

Agree on these two formats before anyone writes code; they let the two of us build in parallel. Drafts to polish:

A vitals reading, sent by the receiver, the simulator or the oximeter reader. Any vital a source doesn't measure is left out.

```json
{
  "patient_id": "p1",
  "ts": "2026-10-18T10:15:03Z",
  "source": "strap",
  "hr": 78,
  "rr_intervals_ms": [764, 771, 768],
  "contact": true,
  "resp_rate": 16,
  "spo2": 97,
  "temp_c": 36.8,
  "sbp": 124,
  "dbp": 80
}
```

A risk result, written by the backend every minute per patient.

```json
{
  "patient_id": "p1",
  "ts": "2026-10-18T10:16:00Z",
  "level": "warning",
  "vital": "hr",
  "reason": "HR 95 despite reported beta-blocker",
  "news2": 3,
  "trend_prob_fast": 0.12,
  "trend_prob_slow": 0.08,
  "red_flags": []
}
```

Open questions to settle:

- [ ] Does the receiver send every message, or batch a few seconds at a time?
- [ ] Do intake records use the same patient IDs and go through the same ingest point?
- [ ] Where does breathing rate get computed: receiver or backend?

## Build order

Steps 1–2 (systems) and step 3 (stats/ML) run in parallel from the start; steps 4–5 bring them together. Each step ends with something that works on its own.

### Step 1: thin slice with fake data — systems

- [ ] Simulator script: several fake patients, readings in the step-0 format
- [ ] Backend (e.g., FastAPI): receive readings, store them, compute one-minute medians
- [ ] Plain NEWS2 check every minute, writing risk results
- [ ] Bare dashboard: patients sorted by risk, refreshed every few seconds over a WebSocket

**Done when:** fake patients appear on the dashboard and change color as their simulated vitals change.

### Step 2: plug in the real strap — systems

- [ ] Run the `bleakheart` example; confirm heart rate and beat intervals arrive
- [ ] Test whether the accelerometer streams at the same time
- [ ] Receiver script: connect, convert to the step-0 format, send to the backend, reconnect on drop
- [ ] Breathing rate from beat intervals, labeled "estimated"
- [ ] Wearer becomes patient 1; the simulator keeps supplying SpO2, temperature and BP for them
- [ ] Record a few minutes of real strap data and hand it to the stats teammate

**Done when:** the wearer's real heart rate shows on the dashboard next to simulated patients.

### Step 3: risk models — stats/ML, starting at step 0

Each plugs into the scoring function from step 1, in this order:

- [ ] Baseline ranges: NEWS2 plus guideline rules first, then the NHANES fit
- [ ] Alert logic with persistence windows
- [ ] Personal baseline
- [ ] Slow trend model (PhysioNet 2019)
- [ ] Fast trend model (MIMIC-III minute data), if time allows

**Done when:** each piece runs on the recorded strap data and its output appears in the risk result.

### Step 4: intake and the LLM — both

- [ ] Intake form: structured fields plus a free-text symptoms box
- [ ] Context adjuster: StepFun extracts facts with quotes; code applies only allowed adjustments

**Done when:** typing "taking beta blockers for my nerves" visibly tightens that patient's heart-rate range.

### Step 5: demo layer — both

- [ ] Replay script that sends an eICU-based deteriorating patient through the simulator
- [ ] Alerts: Photon text, Even G2 heads-up
- [ ] Add-ons: Sentry tracing, Tiger Data storage, a domain
- [ ] Optional: real SpO2 from the fingertip oximeter read by the webcam
- [ ] Demo video, README, Devpost write-up

**Done when:** the full demo script runs start to finish without touching code.

## Notes

- **Espressif challenge is dropped.** Without the ESP32 nothing runs on Espressif hardware. To win it back later, make an ESP32 the Bluetooth-to-Wi-Fi bridge between the strap and the backend.
- **One real patient.** One strap means one live patient; everyone else is simulated. Say so in the pitch.
- **Polar app off.** Disconnect the Polar phone app while testing so it doesn't hold the strap's Bluetooth connection.
- **Hotspot only if needed.** With everything on one laptop the backend can run locally; a phone hotspot matters only if the dashboard or alerts run on another device.
- **Sensor-agnostic pitch.** Any vital the strap can't measure arrives from the simulator in the same format, so a real SpO2 or temperature sensor drops in without changing the backend.
