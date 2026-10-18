# Simulation Layer

Oct 17, 2026 · @Peyton

How the demo gets its patients and events. A simulation is one sample patient plus one fixed-length scripted run in which every vital is synthetic. Interface IDs (I1–I15) refer to [component-map.md](component-map.md); the reasons behind each choice are in [decisions.md](decisions.md).

> Waiting-room scenario (sim-ff): six patients, John Chamberlain replacing U2, 60 simulated minutes, minutes 0-20 replayed as a lead-in on start, then `POST /sim/skip` fast-forwards the sim clock. The lead-in replaces the 120-minute pre-roll for the scenario. Live-mode SpO2/temp filler is dropped.

## Two modes

| Mode | Vitals | Used for |
| --- | --- | --- |
| Live | Strap gives heart rate; the simulator fills SpO2 and temperature (breathing rate is off) | The hardware demo (C2) |
| Run | The simulator sends heart rate, SpO2 and temperature (and a scripted breathing rate that ingest drops); the strap is ignored | The six sample patients and their events |

Real and simulated values are never blended. In run mode ingest drops strap readings.

## What a run contains

- **Streamed every second as I1:** `hr`, `resp_rate`, `spo2`, `temp_c`, plus `contact` true so signal quality keeps the readings.
- **Fixed by the sample patient's intake record (I2):** systolic and diastolic BP, alertness, on-oxygen, pain and ESI level. They add NEWS2 points that never move, so a sicker patient starts with a higher score before any vital changes.
- **Length:** 600 seconds, one reading per second, set by `SimulatorConfig.run_length_s`. Key times in every script are fractions of the run, so a different length rescales all six.
- **Shape:** values at 0, 30, 60 and 100% of the run. Healthy runs stay flat or have one short event (H1 a dip, H2 a climb that recovers); at-risk and critical runs start calm and worsen to the end.
- **Script:** straight lines between values at 0, 30, 60 and 100% of the run, plus a small seeded wobble and device rounding (whole numbers; temperature to 0.1; SpO2 capped at 100). Optional glitches replace one vital for a few seconds.
- **Repeatable:** each script has a fixed seed, so a run is identical every time.

## Sample patients and runs

Six fictional patients, hand-written as I2 records in `backend/simulator/profiles.py`. COPD is left out because I2 cannot say whether a clinician confirmed it, and the 88–92% SpO2 target only applies then.

Values at 0 → 30% → 60% → 100% of the run. Breathing is scripted but ingest drops it, so NEWS2 here scores heart rate, SpO2, temperature and triage only. NEWS2 includes each patient's triage points (C1 has 3: oxygen 2, BP 1; C2 has 5: new confusion 3, BP 2) and is checked against the real scorer in `tests/simulator/test_profiles.py`.

| Run | Tier | Patient | Heart rate | Breathing | SpO2 | Temp °C | NEWS2 | Target alerts |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| H1 Ankle sprain | Healthy | 24 M, no conditions, ESI 4 | 72 → 74 → 73 → 72 | 14 → 14 → 15 → 14 | 98 flat; dips to 90 for 8 s at 50% | 36.6 | 0 → 0 → 0 → 0 | None; the 30-second median absorbs the dip |
| H2 Sore throat | Healthy | 41 F, no conditions, ESI 5 | 78 → 78 → 105 → 80 | 15 → 15 → 22 → 16 | 97 → 97 → 96 → 97 | 36.8 | 0 → 0 → 1 → 0 | None; warning at most |
| U1 Fever on a beta-blocker | At risk | 67 M, hypertension, diabetes, metoprolol | 82 → 88 → 98 → 112 | 18 → 20 → 23 → 26 | 95 → 94 → 91 → 89 | 37.8 → 38.2 → 38.7 → 39.2 | 1 → 2 → 5 → 7 | Urgent from about minute 6, high (7) at the end |
| U2 Asthma flare | At risk | 31 F, asthma, albuterol | 96 → 104 → 118 → 132 | 20 → 24 → 27 → 28 | 95 → 94 → 91 → 89 | 36.9 | 2 → 2 → 5 → 6 | Urgent from about minute 6 |
| C1 Heart failure, short of breath | Critical | 72 M, heart failure, hypertension, on oxygen, ESI 2 | 88 → 90 → 112 → 134 | 20 → 20 → 25 → 30 | 95 → 94 → 92 → 89 | 36.8 | 4 → 4 → 7 → 9 | Below urgent (4) for about 3 min, then high (7+) from about minute 6 |
| C2 Septic-looking, confused | Critical | 58 F, diabetes, cancer, new confusion, ESI 2 | 96 → 108 → 122 → 136 | 20 → 23 → 26 → 30 | 96 → 95 → 93 → 92 | 38.6 → 38.9 → 39.2 → 39.5 | 7 → 8 → 11 → 12 | High from the first minute |

The target alerts are design targets to compare with alert logic (T4) when it exists, not results. The NEWS2 columns are for the script's instantaneous values; the live score uses a 30-second median, so it trails by about 15 seconds.

Replayed before the 30-second period change and with breathing on (60-second median, one-minute summaries, intake from the sample's own record), live NEWS2 first reached. Out of date: re-measure with the live run:

| Run | NEWS2 5 or more | NEWS2 7 or more | I9 level at the end |
| --- | --- | --- | --- |
| H1, H2 | never | never | safe (H2 shows warning for minutes 5 to 8, peak NEWS2 3) |
| U1 | 4:10 | 8:17 | danger (breathing) |
| U2 | 3:57 | 5:19 | danger (breathing) |
| C1 | 3:50 (also a one-off flicker at 0:03 from the wobble, when the window holds only a few seconds) | 3:50 | danger (heart rate) |
| C2 | 0:00 | 0:00 | danger (heart rate); the I9 level reads warning until minute 5 because it ignores triage points |

No run formed a personal baseline in 10 minutes. Fever alone cannot reach the danger tier on the high side (NEWS2 lists only 35.0 °C or below as a 3), so U1 and C2 get there through the total.

## Expected changes with the context adjuster (B3)

The replay table above predates B3. With `on_intake(ctx, i5)` applying the adjuster, sample runs change as below; the table is re-run at C3, not now. Sample records carry no `drug_classes`; intake through the S5 lookup (`backend/intake/lookup.py`) adds them, and the adjuster never fires from the medication list alone.

- **U1** (67, metoprolol, "Fever and chills"): gains age65 and suspected_infection, and beta_blocker once intake runs through the lookup. Temperature starts at 37.8 and danger edges are inclusive, so U1 is in danger from 0:00; the "urgent at 3-6 min" target no longer holds and is re-flagged for the C3 re-run.
- **C1** (72, carvedilol): gains age65, and beta_blocker once intake runs through the lookup.
- **C2** ("Fever, shaking chills"): gains suspected_infection. Breathing 23 becomes danger at about 30% of the run. chemo_fever does not fire (the complaint never mentions chemo), a known gap.
- **H1, H2, U2:** unchanged unless their complaint or age triggers a rule.
- The U1 "fever on a beta-blocker" story needs intake to run through the S5 lookup.

## Trend pre-roll

The fast trend model reads 5, 15 and 30 minute windows and the slow model 1, 3 and 6 hours. A 10-minute run (20 periods) would never fill them, so at run start the simulator hands the risk engine 60 one-minute rows (I6 format), all at once.

- **Contents:** the run's 0:00 values with the same wobble. Starting values, not "calm" ones, because at-risk and critical patients arrive already off normal.
- **Entry point:** a separate risk-engine call, `seed_trend_history(patient_id, rows)`, read by the trend models only. The personal baseline never sees these rows, so its "abnormal on arrival, learn nothing" rule still works. Alert logic, storage and the dashboard never see them either.
- **Why 60:** T5 (the slow model) was dropped, so the fast model's 30-minute windows are the only consumer, and `trend.HISTORY` keeps 60 minutes. The length is `SimulatorConfig.preroll_minutes`.
- **Replace, not append:** `seed_trend_history` replaces the patient's trend history (clean rows only), so a second run never leaves stale or out-of-order rows.
- **Pitch wording:** in a run, the trend models' first two hours of history are scripted, not recorded.

## End of run

The simulator stops sending and sets the run state to ended. That has to look like a pause, not a lost signal.

- Ingest stops recalculating its rolling windows and keeps sending the frozen live window (I13) each second with `run_state` set to ended; it sends no new minute rows (I6).
- The risk engine gets no new minute rows, so nothing decays and no thin-data flag appears. The every-second score repeats the frozen value.
- Alerts are untouched and stay until acknowledged.
- The dashboard shows the last values with a neutral "Run ended" label and offers to start again. Reset returns the run state to live.

## How it connects

| Interface | Direction | Role |
| --- | --- | --- |
| I1 | Simulator → Ingest | Output: four vitals plus `contact` each second, through ingest's entry function with `source` set to simulator |
| I2 | Simulator → Intake form | `GET /sim/profiles/{id}` returns the sample patient's I2 record to prefill the form |
| I12 | Dashboard → Simulator | `scenario_id` is a run id (the sample patient's id, e.g. `u1`); the same start function sits behind `POST /sim/run` |
| I13 | Ingest → Dashboard | New `run_state` field (live, running, ended) |
| Engine | Simulator → Risk engine | `seed_trend_history(patient_id, rows)` at run start |
| I3 | Intake service → Ingest | Sample records carry no wearable (the nurse picks it). After intake the caller passes the patient and the wearable from I3; before intake the sample's own id and the default wearable are used so readings are not dropped |

The simulator talks to ingest and the engine through a small `RunSink` interface (`backend/simulator/models.py`): `ingest(reading, source)`, `set_run_state(patient_id, state)`, `seed_trend_history(patient_id, rows)`. Ingest (S2) and the engine implement it; tests and `scripts/simulate_run.py` use fakes. The in-process call goes through the same entry function the WebSocket handler uses, so runs exercise the same checks as the strap.

## Code layout

| Path | Holds |
| --- | --- |
| `backend/simulator/models.py` | Profile, run script, Sample, RunSink |
| `backend/simulator/profiles.py` | The six sample patients and their scripts |
| `backend/simulator/generate.py` | Script → one Sample per second; pre-roll rows |
| `backend/simulator/player.py` | Plays samples out on a schedule, sets run state |
| `backend/simulator/controller.py` | Start, stop, reset, status for the one active run |
| `backend/simulator/routes.py` | Router for the HTTP side |
| `scripts/simulate_run.py` | Plays a run to the console with the real NEWS2 scorer |
| `tests/simulator/` | Tests |

## Known limits

- **Personal baseline.** It needs 10 minutes of clean data before forming a band, so a 10-minute run ends as it would first appear. Healthy runs show it only with a longer run length.
- **Dashboard lag.** Live scores use a 30-second median, so the NEWS2 badge trails the script by up to 30 seconds; the live numbers (`latest` in I13) do not trail. The steps in the scripts are 3 minutes or longer for that reason.
- **Persistence windows.** The demo config should keep them near 3 minutes or less, or alerts arrive too late to see.
- **Failed runs.** If the sink raises mid-run the run is logged and ends, and the state reads ended like a normal finish.
- **Edited samples.** If the nurse edits a sample patient's fields before submitting, the NEWS2 targets above no longer hold.
- **Not a clinical claim.** Values are chosen to exercise the pipeline, not to model a disease.

## Status

Backend built, unit-tested and merged. **Integration testing is blocked** until the pieces below exist; it has not been done. What was checked without them: each run replayed through the real risk engine with an emulated 60-second window (results above), the JSON schemas, the I1 wire format, and the routes on a throwaway app.

Built: models, profiles, generator, pre-roll, player, controller, routes, console run script.

## Blocked: integration checks to run later

| Needs | Check |
| --- | --- |
| Ingest, S2 | Start a run through an app that mounts the router. Ingest sees readings with `source` simulator, drops strap readings during the run, and still merges strap and simulator in live mode. I13 goes out each second with `run_state` running, then ended; at the end the window is frozen and no I6 rows follow. |
| Engine `seed_trend_history` (exists, T6) | Called once with 60 rows before the first reading. The personal baseline stays population (the pre-roll must not reach `on_period`). |
| Alert logic, T4 | Alerts match the target alerts above: none for H1 and H2, urgent then high for U1, U2, C1, high at once for C2. Alerts stay up after the run ends. |
| Dashboard and I12 handler, S4/S6 | The run button reaches `controller.start`; the screen shows the last values and "Run ended" after the data stops. |
| Intake form and service, S5 | Prefill from `GET /sim/profiles/{id}`, `POST /intake`, then a run with the returned patient and the I3 wearable. |
| Strap, live mode | Run mode ignores a connected strap. Live mode merges real heart rate and breathing with simulated SpO2 and temperature (C2). |
| Everything | One full 10-minute real-time run from button to "Run ended". |

Built by S2: the app that mounts the router, the I12 handler, ingest's side of `RunSink` and the run-mode rules (`backend/app.py`, `backend/ingest/`). Not built: the form's "Load sample patient" and the dashboard's run button and "Run ended" label (S5, S6), live-mode filler (S3 for C2), and the engine's `seed_trend_history` (T6; ingest skips the call until it exists).
