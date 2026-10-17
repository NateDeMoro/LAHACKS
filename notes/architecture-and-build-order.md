# Waiting Room Vitals Monitor: Architecture and Build Order

Oct 17, 2026 · @Nate

The Polar H10 chest strap connects straight to a laptop over Bluetooth. The demo has one patient, the wearer. The strap supplies real heart rate and breathing rate; the simulator fills in the vitals it can't measure (SpO2, temperature, the triage blood pressure) from the wearer's predicted ranges, shown alongside the real ones. Event buttons on the dashboard play scripted scenarios: any vital the script covers replaces the real reading for the event, then hands back to the strap. We say in the pitch which values are real; the data carries no tag. Blood pressure is a single reading taken at triage. We build a crude end-to-end pipeline on fake data first, then swap in the strap and improve each piece.

## Components

&#91;embedded content: components · strap on a laptop, no ESP32\]

The strap and the simulator write the same reading format into one ingest point, which merges them per vital, so replacing a simulated vital with a real sensor (such as the optional oximeter) changes nothing downstream. The backend computes one-minute medians and hands them to the risk engine; the risk engine and alert logic run every minute; the dashboard updates from the risk results.

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

Agree on these formats before anyone writes code; they let the two of us build in parallel. Shared rules:

- **Units:** metric (kg, cm) and Celsius everywhere.
- **Timestamps:** LA local time with its UTC offset, e.g. `2026-10-18T10:15:03-07:00`, so time math stays correct.
- **Missing values:** every field is nullable; a null is ignored downstream, never filled in.
- **Transport:** WebSocket from the receiver or simulator to the backend, and from the backend to the dashboard. The dashboard updates when new risk results arrive; specifics later.

### Intake record

Created by the intake form. The patient ID is generated automatically; the nurse then assigns a wearable to that patient (e.g. "wearable 10"), and the backend maps readings from that wearable to the patient.

```json
{
  "patient_id": "p1",
  "wearable_id": 10,
  "arrival_ts": "2026-10-18T10:02:00-07:00",
  "age": 67,
  "sex": "female",
  "height_cm": 163,
  "weight_kg": 72,
  "pregnant": false,
  "conditions": ["hypertension", "diabetes"],
  "medications": ["metoprolol", "sertraline"],
  "chief_complaint": "fever and chills for 2 days, feel dizzy",
  "triage": {
    "sbp": 128,
    "dbp": 78,
    "alertness": "alert",
    "pain": 4,
    "on_oxygen": false,
    "level": 3
  }
}
```

- **Sex:** male or female (NHANES records only these two).
- **Conditions:** checkboxes for every condition with enough NHANES participants to fit a shift: hypertension, asthma, cancer, diabetes, thyroid disease, COPD, liver disease, heart disease (coronary heart disease, angina and heart attack combined), stroke, heart failure. Kidney disease pending a check of its NHANES file. Ticking COPD alone does not switch the SpO2 target; that needs clinician confirmation (training plan, section 1).
- **Medications:** names as typed; the backend maps each to a drug class using NHANES RXQ\_DRUG.
- **Alertness:** alert, new confusion, responds to voice, responds to pain, unresponsive.
- **Pain:** 0–10. **Triage level:** ESI 1–5, assigned by the nurse.
- **Blood pressure:** taken once at triage, never repeated.
- **Starting vitals:** heart rate and breathing rate are the median of the wearable's first 1–2 minutes of clean signal; SpO2 and temperature start from simulated values. These seed the personal baseline.
- **Triage blood pressure:** simulated for the demo from the wearer's predicted range.

### Vitals reading

Sent by the strap receiver, one message per heart-rate notification, about once a second. Each message carries every beat interval since the last one, which is all breathing rate needs. The raw ECG (130 Hz) is streamed only if we add a live waveform to the dashboard.

The simulator sends the same format with the same wearable ID, but only the vitals it is filling or scripting. Ingest uses the simulator's value for any vital it sent in the last few seconds, otherwise the strap's.

```json
{
  "wearable_id": 10,
  "ts": "2026-10-18T10:15:03-07:00",
  "hr": 78,
  "rr_intervals_ms": [764, 771],
  "contact": true,
  "resp_rate": null,
  "spo2": null,
  "temp_c": null
}
```

### One-minute summary

The backend computes the median of each vital over each minute and hands the result to the risk engine. A minute with no clean data is null.

### Risk result

Written by the backend every minute per patient. `news2_points` holds the 0–3 points for each NEWS2 part, so the dashboard can show which vital drove the score.

```json
{
  "patient_id": "p1",
  "ts": "2026-10-18T10:16:00-07:00",
  "level": "warning",
  "vital": "hr",
  "reason": "HR 95 despite reported beta-blocker",
  "news2": 3,
  "news2_points": {"resp_rate": 2, "spo2": 0, "on_oxygen": 0, "sbp": 0, "hr": 1, "alertness": 0, "temp_c": 0},
  "trend_prob_fast": 0.12,
  "trend_prob_slow": 0.08,
  "red_flags": []
}
```

### Scenario trigger

Sent by the dashboard to the simulator when an event button is clicked: scenario ID, patient ID, start time. Each scenario is a scripted path for some vitals over a few minutes. The event list comes later.

### Decided later

- Context adjuster output format (pending more discussion).
- Per-patient ranges: computed inside the risk layer from NEWS2, NHANES and the guideline rules (training plan).
- Alert acknowledgment state, during the demo-layer step.

Open questions to settle:

- [ ] Where does breathing rate get computed: receiver or backend?

## Build order

Steps 1–2 (systems) and step 3 (stats/ML) run in parallel from the start; steps 4–5 bring them together. Each step ends with something that works on its own.

### Step 1: thin slice with fake data — systems

- [ ] Simulator script: one fake patient with an intake record, readings in the step-0 format
- [ ] Backend (e.g., FastAPI): receive readings over a WebSocket, store them, compute one-minute medians
- [ ] Plain NEWS2 check every minute, writing risk results
- [ ] Bare dashboard: patients sorted by risk, updated over a WebSocket as risk results arrive

**Done when:** fake patients appear on the dashboard and change color as their simulated vitals change.

### Step 2: plug in the real strap — systems

- [ ] Run the `bleakheart` example; confirm heart rate and beat intervals arrive
- [ ] Test whether the accelerometer streams at the same time
- [ ] Receiver script: connect, convert to the step-0 format, send to the backend, reconnect on drop
- [ ] Breathing rate from beat intervals, labeled "estimated"
- [ ] Wearer becomes the patient through an intake record; the simulator fills SpO2, temperature and triage BP from the wearer's predicted ranges
- [ ] Ingest merges strap and simulator readings per vital
- [ ] Record a few minutes of real strap data and hand it to the stats teammate

**Done when:** the wearer's real heart rate and breathing rate show on the dashboard next to simulated SpO2 and temperature.

### Step 3: risk models — stats/ML, starting at step 0

Each plugs into the scoring function from step 1, in this order:

- [ ] Baseline ranges: NEWS2 plus guideline rules first, then the NHANES fit
- [ ] Alert logic with persistence windows
- [ ] Personal baseline
- [ ] Slow trend model (PhysioNet 2019)
- [ ] Fast trend model (MIMIC-III minute data), if time allows

**Done when:** each piece runs on the recorded strap data and its output appears in the risk result.

### Step 4: intake and the LLM — both

- [ ] Intake form: the step-0 intake fields, auto patient ID, wearable assignment, free-text chief complaint
- [ ] Medication names mapped to drug classes (RXQ\_DRUG)
- [ ] Context adjuster: StepFun extracts facts with quotes; code applies only allowed adjustments

**Done when:** typing "taking beta blockers for my nerves" visibly tightens that patient's heart-rate range.

### Step 5: demo layer — both

- [ ] Scenario player and event buttons (event list to be decided); scripted vitals replace the real ones during an event
- [ ] Alerts: Photon text, Even G2 heads-up
- [ ] Add-ons: Sentry tracing, Tiger Data storage, a domain
- [ ] Optional: real SpO2 from the fingertip oximeter read by the webcam
- [ ] Demo video, README, Devpost write-up

**Done when:** the full demo script runs start to finish without touching code.

## Notes

- **Espressif challenge is dropped.** Without the ESP32 nothing runs on Espressif hardware. To win it back later, make an ESP32 the Bluetooth-to-Wi-Fi bridge between the strap and the backend.
- **One patient.** The demo shows only the wearer, with real and simulated vitals side by side. Say in the pitch which are which.
- **Polar app off.** Disconnect the Polar phone app while testing so it doesn't hold the strap's Bluetooth connection.
- **Hotspot only if needed.** With everything on one laptop the backend can run locally; a phone hotspot matters only if the dashboard or alerts run on another device.
- **Sensor-agnostic pitch.** SpO2 and temperature already have fields in the reading format, so a real sensor drops in without changing the backend.
