# Build Order

Oct 17, 2026 · @Nate

Three lanes run in parallel from the start: systems, stats, and a shared lane for the context adjuster. They meet at four checkpoints, and each checkpoint leaves the demo runnable. Within a lane, the riskiest integration goes first. Interface IDs (I1–I15) refer to [component-map.md](component-map.md).

## Lanes and checkpoints

```mermaid
flowchart LR
  P0["P0 · Both<br/>Shared contract models I1–I15<br/>Stub risk engine: plain NEWS2<br/>Fixture files: I6/I13 rows from eICU"]

  subgraph SYS[Systems lane]
    direction LR
    S1["S1 Strap receiver<br/>HR, beat intervals, breathing rate → I1"]
    S2["S2 Ingest service<br/>I1 in · merge · I6 + I13 out"]
    S3["S3 Simulator<br/>sample patients + runs, live filler"]
    S4["S4 Dashboard<br/>live vitals I13 + NEWS2 I14"]
    S5["S5 Intake form + service<br/>I2 → I3, I4 · med lookup"]
    S6["S6 Run buttons<br/>load sample, start run I12"]
    S8["S8 Add-ons<br/>Tiger Data, Sentry, Vultr, domain, Fetch.ai"]
  end

  subgraph STATS[Stats lane]
    direction LR
    T1["T1 NEWS2 scorer<br/>I13 → I14, per-part points"]
    T2["T2 Baseline ranges<br/>NHANES fit → ranges.json, I8"]
    T3["T3 Personal baseline<br/>I6 → narrowed I8"]
    T4["T4 Alert logic<br/>I9 → I10"]
    T6["T6 Fast trend model<br/>MIMIC-III minutes, 15 min only, if time"]
  end

  subgraph BOTH[Shared lane]
    direction LR
    B1["B1 step-5-preview call<br/>JSON Schema output"]
    B2["B2 Test set<br/>~100 labeled complaints"]
    B3["B3 Context adjuster<br/>I4 → I5 + I15"]
  end

  G1{{"C1 Thin slice<br/>simulator → ingest → stub → dashboard"}}
  G2{{"C2 Real strap live<br/>real HR + breathing beside simulated vitals"}}
  G3{{"C3 Real risk engine<br/>intake → ranges → scores → alerts"}}
  G4{{"C4 Full demo<br/>runs, fast trend, add-ons"}}

  P0 --> S1 & S2 & T1 & B1
  S2 --> S3 --> S4
  S1 --> G2
  S4 --> G1
  T1 --> G1
  G1 --> G2
  G2 --> S5 --> G3
  T1 --> T2 --> T3 --> T4 --> G3
  B1 --> B2 --> B3 --> G3
  G3 --> S6 --> G4
  T4 --> T6 --> G4
  S8 --> G4
```

Read left to right: everything in one column can be built at the same time. A checkpoint needs every arrow into it before the two lanes plug together.

## Steps

| Step | Owner | Needs | Done when |
| --- | --- | --- | --- |
| P0 Contracts and stubs | Both | — | Shared models for I1–I15 exist; a stub risk engine returns plain NEWS2 as I9/I14; eICU fixture rows load as I6/I13 |
| S1 Strap receiver | Systems | P0 | bleakheart prints HR and beat intervals; receiver sends I1 with breathing rate; reconnects on drop. Done: receiver/, scripts/hardware/ |
| S2 Ingest service | Systems | P0 | Accepts I1 over WebSocket, merges sources per vital, emits I13 each second and I6 each minute; run mode drops strap readings and freezes when a run ends (component-map, Simulator runs). Done: backend/app.py, backend/ingest/, tests/ingest/ |
| S3 Simulator | Systems | P0 (S2 to plug in) | Six sample patients play fixed-length runs through the `RunSink` interface, with run state and a 120-minute trend pre-roll. Done: backend/simulator/, scripts/simulate_run.py. Still to build: the live-mode filler of SpO2 and temperature for C2, and ingest's side of the sink (S2). Integration testing is blocked on S2, T4, S5 and S6 (checks listed in simulation-layer.md) |
| S4 Dashboard | Systems | S3 | Shows live vitals and NEWS2 updating every second from the stub |
| T1 NEWS2 scorer | Stats | P0 | P0 stub already scores the full table; T1 checks it against reference cases, covers edge cases and missing parts, and owns scoring from here. Done: NaN rejection, tests/risk_engine/test_news2.py |
| **C1 Thin slice** | Both | S4, T1 | Simulated vitals flow end to end and NEWS2 moves on the dashboard |
| **C2 Real strap live** | Systems | C1, S1 | The wearer's real HR and breathing rate show next to simulated SpO2 and temperature |
| S5 Intake form + service | Systems | C2 | Submitting the form creates a patient, assigns the wearable (I3) and produces I4 with drug classes |
| T2 Baseline ranges | Stats | T1 | NHANES quantile fit written to ranges.json; engine builds I8 from I4. Done: training/fit_ranges.py, backend/risk_engine/ranges.py |
| T3 Personal baseline | Stats | T2 | I6 rows narrow the safe band; danger limits move only via I5. Done: backend/risk_engine/baseline.py (hr and breathing) |
| T4 Alert logic | Stats | Step A | Recorded I9 rows produce I10 alerts with persistence windows and one alert per problem. Done: backend/risk_engine/alerts.py, tests/risk_engine/test_alerts.py, training/tune_alerts.py, replay_fixture --alerts |
| B1 step-5-preview call | Both | P0 | A test call returns valid JSON matching the I5/I15 schema. Done: backend/llm.py, backend/adjuster/proposal.py, scripts/stepfun_smoke.py |
| B2 Test set | Both | B1 | About 100 labeled chief complaints, including negations. Done: fixtures/adjuster (30 dev, 70 test), models/rules.json, notes/adjuster-labeling-guide.md |
| B3 Context adjuster | Both | B2 | I4 in, I5 to the engine, I15 to the evaluation log; quote check enforced; scored on the test set. Done: backend/adjuster/ (rules.py, prompt.py, adjuster.py), ranges.apply_i5 wired into on_intake, scripts/score_adjuster.py (selftest, offline, live); test split precision 1.000, recall 0.982 (decisions.md B3) |
| **C3 Real risk engine** | Both | S5, T4, B3 | A typed intake changes the wearer's ranges, and live scoring and alerts run on the real engine |
| S6 Run buttons | Systems | C3 | The intake form prefills a sample patient and a dashboard button starts its run; scores react and the end shows as a pause |
| Step A Trend wiring | Stats | T3 | I9 carries per-vital levels and trend fields (null with the stub), I10/I11 contracts and typed alert/trend config exist, `trend.py` and a stub `fast_model.py` are wired into the engine. Done: backend/risk_engine/trend.py, tests/risk_engine/test_trend.py |
| T6 Fast trend model | Stats | Step A | The 15 min model (or the better simple baseline) replaces the stub; beats both baselines or a baseline ships; tier and reason appear in I9 |
| S8 Add-ons | Systems | any time | Tiger Data stores readings, Sentry tracing + logs, hosted on Vultr behind a domain, Fetch.ai agent answers in ASI:One |
| **C4 Full demo** | Both | S6 (T6, S8 if done) | The demo script runs start to finish without touching code |

## Order of risk

Riskiest first in each lane, because each could force a plan change:

1. **S1:** the strap's Bluetooth connection and breathing rate from beat intervals.
2. **B1:** access to step-5-preview and its structured output.
3. **T2:** whether the NHANES fit gives sensible ranges by profile.
4. **T6:** the MIMIC-III download size, which is why it's last and optional.
