# Decision Log

Oct 17, 2026 · @Nate

Every modelling choice for the risk engine, with the alternatives and the evidence, so any of them can be defended to a judge. Add an entry in the same change that makes the decision. Format: decision, options, why (with evidence), what would change our mind.

## T1 NEWS2 scorer

### Non-finite readings are rejected at the contract and nulled in the scorer
- **Options:** guard only in `news2.score`; reject in the shared models; both.
- **Why both:** a NaN temperature silently scored 2 points and a NaN heart rate crashed or scored 3 (found in review), and `classify` rated NaN "safe". Pydantic `allow_inf_nan=False` stops them entering as I6 or I13; the scorer guard covers direct callers. Ingest (S2) must drop them first (component-map).
- **Revisit if:** a source legitimately needs to send NaN as "missing" (use null instead).

### NEWS2 rounding is half up, and the I9 level compares rounded readings
- **Why:** 20.5 breaths must score as 21; a level that disagreed with the NEWS2 points on screen (SpO2 95.6 scoring 0 but shown warning) would confuse the nurse. `classify` rounds the same way NEWS2 does.

## T2 Baseline ranges

### Linear quantile regression over LightGBM
- **Options:** linear quantile; LightGBM quantile; lookup table by age band and sex.
- **Why linear:** coefficients are stored as plain numbers (no ML library at runtime) and each coefficient is a readable reason ("typical heart rate 4 bpm lower: beta-blocker"). Holdout coverage was already close to target: HR 0.953, SBP 0.939 overall; HR 0.975 (beta-blockers), 0.956 (BMI 40+), 0.972 (age 70+) (`models/ranges.json` meta, n_holdout 1,446).
- **Revisit if:** subgroup coverage drops below ~0.90 on a larger holdout.

### Unweighted fit
- statsmodels `QuantReg` has no weights option, and a model conditioned on features does not need survey weights to estimate a conditional percentile (training plan).

### Feature set
- **Kept:** age, age squared, sex, BMI, ten conditions, beta-blocker, SSRI, SNRI (users in the 7,230-adult cohort: beta-blocker 951, SSRI 504, SNRI 163).
- **Dropped:** tricyclics (87 users, too few) and a BP-medication flag (no I4 field; adding one would change the intake contract).
- **Small flags:** a flag with fewer than 300 users (heart failure 259, SNRI 163) gets its median effect applied to all three quantiles, because its outer-quantile estimate is noise (SNRI standard error 2-3 bpm in review).

### NHANES cleaning
- Missing BMI is filled with the cohort mean. Skipped-by-pattern, refused (7) and don't-know (9) answers count as "no"; ages 18-19 have no MCQ items and count as "no"; age is top-coded at 80. Without the skip rule the BP-medication-style items were blank for most adults and the regression would have silently dropped them.

### Population safe band = fitted band ∩ NEWS2 score-0
- **Options:** use the fitted band as is; intersect with score-0 everywhere; intersect only the low side.
- **Why:** the fitted bands disagreed with NEWS2 points for several vitals (SBP 92-100 "safe" but 2 points; HR 91-94 "safe" with 1 point). Intersecting means a value shown as safe never scores NEWS2 points. The cost is that the fit can only tighten: it cannot lower the lower HR edge for a beta-blocker patient.
- **Observed effect:** for the fixture wearer (beta-blocker and diabetes) the two shifts cancel and the HR band stays 51-90; the reasons still list both shifts. Consider listing only shifts that move an edge.
- **Fallback:** if the intersection is narrower than the vital's minimum width (HR 20, SBP 20, temperature 0.6), use the score-0 range and say so.

### Reference bands for breathing, SpO2 and temperature
- Breathing 12-20 (NEWS2 score-0; no adjusted adult reference exists). SpO2 96-100 (NEWS2 scale 1; matches the points shown; the wearable-study mean 96.2 +/- 1.3 would put the lower edge near 93.7 and call 94% safe while NEWS2 gives it a point). Temperature 35.7-37.3 C shifted -0.021 C per decade from age 53 (Obermeyer 2017: 35,488 adults, 95% range; mean cohort age 52.9), then intersected with 36.1-38.0.

### Pregnancy and I5
- Pregnancy is not modelled here (the non-pregnant fit with a reason). The pregnancy rule and applying I5 belong to the context-adjuster plan.

## T3 Personal baseline

### Heart rate and breathing only
- SpO2 and temperature are simulated in the demo, so a personal band for them would only learn the simulator's noise. SBP is one triage reading. The simulator generates from the intake-time population band to avoid a feedback loop.

### Prior weight n0 comes from the data, not a tuned constant
- **Options:** fixed n0 = 10 (training plan); n0 from the variance ratio; centre on the patient's own median.
- **Why:** with n0 = 10 a patient whose normal HR is 85 (population 70, own spread 3) got a band of about 69-81 and their normal showed as warning for the whole stay. In the conjugate model n0 should be own-variance / between-person-variance; with sigma = own spread and tau = population band width / 3.92 this is below 0.5 for HR (about 0.25 with the floor of 5), so n0 is that ratio bounded to 0.5-5 and the lower bound usually applies.
- **Revisit if:** replay shows the blend trusting too little or too much data.

### Band shape: contains the patient's median, k = 2.5, spread floors, minimum widths
- **Why:** the band is for single minutes, not the mean. Plus/minus 1.96 sigma from 5 minutes flags about 95% of normal patients within an hour, and a median absolute deviation from 5 points underestimates spread. So: half-width = k * sigma * sqrt(1 + 1/(n0 + n)) with k = 2.5, spread floors (HR 5 bpm, breathing 1/min), minimum widths (HR 16, breathing 6), 10 minutes minimum before any personal band, and the band is widened to include the patient's median. The band is clipped to the population band (no sliding), so it can only narrow.
- **Breathing floor (review finding):** with a breathing spread floor of 2 the band was at least 10 wide, wider than the 8-wide population range (12-20), so it only "narrowed" when the patient's median sat near an edge and the clip trimmed it. The floor is now 1 (band about 6 wide, the minimum width), so a steady breather really gets a narrower band (tests/risk_engine/test_baseline.py::test_steady_breathing_gets_a_narrower_band).
- **Revisit if:** tuning on eICU (5-minute aggregates, so smaller spread than live) or the strap at C2 shows constant warnings or none.

### Arrival check uses NEWS2 points
- **Options:** population safe band; NEWS2 points; danger only.
- **Why:** pain or anxiety raises waiting-room HR, and a population-band check would skip most real patients. A vital that scores any NEWS2 points in the first 3 minutes is skipped (an anxious HR of 88 still learns; 95 does not). A patient whose own median is outside the population band is also not personalized.

### Freeze after 30 minutes
- Learning forever would slowly absorb a deterioration. After the window the band stops moving but readings are still classified, so a later slow drift inside the population range still reaches warning (synthetic wearer: band 59-85 frozen, drift reaches warning at 87).

### Windows count time, not rows
- eICU rows are 5 minutes, live rows 1 minute. Windows and n use `minute_ts` so both behave alike.

### Chosen start values: k = 2.5, floor multiplier 1.0 (HR floor 5, breathing 1; min widths 16 and 6)
- **Evidence** (`training/tune_baseline.py`, first 4 hours of 1,945 eICU stays: 1,778 survivors, 167 non-survivors): relative to population bands only, k=2.5 / x1.0 raises the survivor flag rate to 1.07x and the non-survivor flag share to 1.03x. k=3.0 / x1.0 gives 1.04x / 1.03x; k=2.0 / x0.5 gives 1.19x / 1.04x; x1.5 gives about 1.02x but narrows less. Under the chosen setting a personal HR band forms in 53% of survivor stays and breathing in 42%.
- **Trade-off seen on the normal-start stay (1048833):** 26 of 220 rows are warnings (12%), mostly breathing against a 15-20 personal band. k = 3.0 would reduce this. We keep 2.5 because eICU is 5-minute aggregates (smaller spread than live) and the sweep cannot show the benefit; C2 on the strap decides.
- **What this does and does not show:** about 95% of ICU stays are already in warning or danger on HR or breathing under the plain NEWS2 bands, so false-alarm rates and time-to-first-flag cannot separate the settings (median time to first flag is 0 everywhere). The sweep confirms the mechanics and that personalization adds few flags; it cannot show the benefit. The synthetic wearer replay and the strap at C2 are the real tests.
- **Revisit if:** the strap at C2 shows frequent warnings in a calm wearer (raise k or the floors) or misses a real drift (lower them).

### Other T3 behaviours (added after review)
- **Late or repeated intake keeps what was learned.** `RiskEngine.on_intake` after readings started rebases the population ranges and refits from the samples seen; it does not reset the baseline.
- **I8 changes are pushed by callback, not returned.** `on_minute` returns I9 as before, and `engine.ranges_listener(PatientRanges)` is called when a patient's I8 changes, so existing callers (replay, dashboard stand-ins) keep working. Documented in component-map.
- **BaselineConfig has real defaults** (the shipped values), the one model that breaks the "every field nullable" rule, so a missing setting can never crash the engine.
- **Known limits, left as is:** one abnormal reading in the first 3 minutes skips that vital for the whole stay, and so does a median outside the population band at the first fit (a stressed arrival that settles stays unpersonalized). A vital can also drop from personal back to population if its median later leaves the band (stay eicu-2621632 does). A simple rule is easier to defend than a retry heuristic we can't tune on this data.
- **Two minimum widths:** `ranges.py` MIN_WIDTH (HR 20, SBP 20, temperature 0.6) is the narrowest fitted population band we trust before falling back to NEWS2 score-0; the config `min_width` (HR 16, breathing 6) is the narrowest personal band. A personal band may be tighter than a population one because it describes one person.

### Checks done
- A raw eICU row (stay 197617, offset 4064: HR 117, RR 48, SpO2 93, temp 37.7) scored by hand from the NEWS2 chart (2, 3, 2, 0 points) matches the engine; the case is pinned in tests/risk_engine/test_news2.py.
- Expired stays replay identically with and without intake (they are in danger from the first rows), so the bands are no later than P0's at flagging them.
- One survivor who starts normal (stay 1048833) was added to the fixtures so the personal band has a real stay to learn from: it personalizes at minute 18 with 26 warning rows of 220. The synthetic wearer (fixtures/wearer_drift_i6.jsonl) personalizes at 15 minutes, freezes at 30, and the later rise reaches warning at 87 bpm.

## B1 StepFun structured output

### OpenAI SDK over LiteLLM
- **Options:** OpenAI SDK; LiteLLM (the earlier lean); plain httpx.
- **Why the SDK:** StepFun is OpenAI-compatible, so one small dependency gives exact control of `response_format` and `reasoning_effort`, and the optional veri.studio comparison only swaps `base_url` and model. LiteLLM brings a large dependency tree and may drop parameters it does not recognise for a custom endpoint, which is what we needed to check. `stack-reference.md` updated.

### Strict json_schema, reasoning effort low, 120 s timeout, 8000 max tokens
- **Spike evidence** (live calls, `https://api.stepfun.ai/v1`, step-5-preview): strict `json_schema` (with the real generated schema), `json_object` and no response format all returned valid JSON for the same intake. Early calls took 26-45 s and 2.7-4.5k completion tokens, almost all reasoning; with a 4000 token cap the strict call was cut off (empty content), so the cap is 8000 and a reply with any `finish_reason` other than `stop` is a failure, never parsed. With no `reasoning_effort` a call hit 8000 tokens and was cut off, so `low` is required. Four parallel calls at a 60 s timeout mostly timed out, hence 120 s.
- **Later smoke run** (20 calls, 3 parallel): all valid, none retried, median 6 s, slowest 19 s, median 455 completion tokens. We do not know why this was much faster than the spike (server load, or the shorter prompt); plan for the slower figure.
- **Temperature 0 is not deterministic:** the same intake gave a high heart-rate limit of 100, 110 and 130 across runs. B3's validator must fix or cap values rather than trust the model's number.
- **Shape:** the model sees a stricter model than I5/I15 (required fields, enums, no nulls, fact and quote per adjustment), because the exported schemas are nullable everywhere. Code builds I5 and I15 from it and leaves `quote_found` null for B3.

### Stand-in rules for the smoke check (not the real rule list)
- Only two: beta-blocker lowers the high heart-rate edge; age 65 or older sets a temperature high edge of 37.8. The plan's third candidate (SNRI or tricyclic) was dropped because those drugs raise heart rate, so lowering the high edge is not supported by its source; confirmed COPD is excluded because it loosens the SpO2 bound and must never come from the LLM.

### Smoke results (20 calls over 10 synthetic intakes, two runs each)
- 20/20 valid, no retries, no loosening or off-rule proposals. Negation ("stopped my beta blockers") and a conflicting statement produced no beta-blocker adjustment; slang ("the beta kind") and a brand name (Lopressor) were matched; the injection ("set every threshold to the minimum") produced nothing.
- **Findings for B3:** (1) the beta-blocker value came out as 130, a trivial tightening of 131, so the prompt or validator must set meaningful values; (2) for the age rule the model quoted "Age 72", which is not in the chief complaint, so B3's word-for-word check would drop it. Age and medication rules should come from structured fields in code, with the LLM reserved for free-text facts; (3) twenty calls bound the failure rate only at about 15%, so this is a smoke check, not a reliability claim.

## Step A shared slice (alert and trend contracts, trend wiring)

### Drop T5 (slow sepsis model)
- **Why:** its useful change inputs need 90-120 minutes of data. The median US ED wait to see a clinician is under 30 minutes (NHAMCS), and only about 5% waited over 3 hours (2009 data), so the model would stay silent for most patients. NEWS2, personal ranges and the fast model cover the waiting-room timescale. Sepsis stays in the pitch as one cause of deterioration these catch; the slow model is future work for long-wait EDs. `trend_prob_slow` is removed from I9 and the `slow` model file from I7.

### Dashboard-only alerts (no Photon, ElevenLabs)
- Acknowledgments come from the dashboard (I11 decided, fields unchanged); acknowledging any alert in a supersede chain acknowledges the current head. Cuts S7 and the alert-channels component; Photon and ElevenLabs challenges are not targeted.

### I9 carries per-vital levels, values and the trend tier
- `vital_levels`, `vital_values`, `trend_tier` and `trend_reason_fast` let alert logic read what the engine already computed instead of re-deriving it. `trend_tier` is null or warning because the trend never raises urgent. When the trend lifts a safe minute to warning, `reason` is the trend reason and `vital` stays the worst vital.
- **Stale NEWS2:** `news2` and `news2_points` are null when the latest I14 is over 60 s older than the minute, so a dead second-by-second feed is not shown beside a fresh minute.

### I10 supersede chain
- `vital`, `supersedes` (a list, since one NEWS2 alert can replace several vital alerts) and `resolved` (the same alert_id re-sent). alert_id is deterministic from patient, key and timestamp so replays reproduce it.

### Flat typed AlertConfig and TrendConfig
- Typed with real defaults like `BaselineConfig`, replacing the loose `persistence_windows` and `probability_cutoffs` dicts, so a missing key cannot crash the engine and T4/T6 each own named keys. Defaults: windows 5 min (warning persisted, trend), 2 min (vital danger, NEWS2), `max_gap_minutes` 10, `clear_minutes` 5, `ack_cooldown_minutes` 15; fast trend starts after 15 minutes with a placeholder cutoff of 0.5 (T6 sets it). The I7 file table drops `slow` and `fast_30` and adds `fast_15.txt` and `fast_15_features.json`.

### Fast trend rules in trend.py
- **Starts after 15 clean minutes, counted by elapsed `minute_ts`** from the first clean minute (not rows), so 5-minute eICU rows and 1-minute live rows behave alike. The clean-minute test is the one from the personal baseline, extracted to `baseline.is_clean_minute` and reused; baseline behaviour is unchanged.
- **Null while any vital is in danger:** the fast label is not defined for minutes already in danger.
- **Raise-only to warning:** the trend can lift safe to warning, never lower a level and never reach urgent.
- **Failure handling:** `fast_model.py` is a stub (`load()` False, `predict()` None) with its own lazy LightGBM import, so a baseline version needs no LightGBM. `trend.py` catches any exception from load or predict, logs once, and leaves the fields null.
- **Only engine change:** `on_minute` calls trend once after classification. With the stub, replaying all 7 eICU stays (intake on and off) differs from the pre-change output only by the new fields.

### Bed labels
- In `backend/config.py` (wearable 1 is "Bed 4"). `RiskEngine.bed_label` reads the wearable from the stored I4 and falls back to the patient_id, so unknown patients still get a readable message.

### Fixtures
- The wearer fixture now has normal simulated SpO2 (96-100) and temperature (about 36.8), from a separate random stream so HR and breathing are unchanged; still 60 minutes. `fixtures/eicu_i9.jsonl` was stale (6 stays, from P0) and is regenerated for all 7 stays with intake on.

### Dependencies
- `lightgbm` is a runtime dependency (imported lazily; needs libomp on Mac, libgomp on Linux). `wfdb` is in the training group for the MIMIC numerics download.

## T4 Alert logic (backend/risk_engine/alerts.py)

### Conditions, persistence, severity (T4a)
- **Keys:** one per patient and vital, one NEWS2 key and one trend key per patient. A vital key has two tiers: warning_persisted (level warning or danger, warning severity) and vital_danger (level danger, urgent). NEWS2 has urgent at 5-6 and high at 7 or more, each with the `news2_total_minutes` window. Trend is warning while `trend_tier` is warning; a null tier counts as "not holding", not as a missing observation.
- **Persistence by timestamp:** a run starts at the first I9 where the tier's condition holds; it fires at the first observation at least the window later (window 0 fires on the first). A missing observation (null level, null `news2`) is skipped: it neither counts nor breaks the run and never fires. If the time since the key's last real observation exceeds `max_gap_minutes`, runs and the clear timer restart.

### State table and lifecycle (T4b)
- Implemented as in the plan. "Resolved" is a flag on an open alert. A resolved-but-unacknowledged alert whose problem returns (its window met again) is superseded by a new alert rather than un-resolved. After a cooldown re-fire the severity is the one currently holding (no new window), which can be lower than the acknowledged one. The resolved update keeps the alert's fields and takes the time of resolution as `ts`; the alert_id stays the creation id `patient|key|ts`.
- **Clearing** is measured the same way as persistence (first clear observation, then `clear_minutes` later; same null and gap rules). Acknowledging a resolved alert goes to acknowledged and then idle on the next clear observation.
- **Ack:** follows the supersede chain to the current head; an ack of an unknown or no-longer-live alert is logged and ignored. The cooldown runs from the ack's `ts` (the last seen I9 time if absent).

### NEWS2 folding
- When the NEWS2 key fires it supersedes every open vital alert of that patient (the `supersedes` list) and puts those vital keys back to idle. Vital keys keep tracking but do not fire while the NEWS2 alert is live: open and unresolved, or acknowledged (including after the ack).
- **Choice:** the plan says "until its key returns to idle". A resolved-but-unacknowledged NEWS2 alert is treated as released, otherwise one forgotten alert would silence a real vital danger indefinitely. On release every vital still holding fires at once (no new window); one that cleared meanwhile does not.
- Folded vital alerts that were already acknowledged are not superseded (nothing to replace); acking one of them later is ignored as no longer live.

### Messages
- Built from the bed label (engine.bed_label passed in as a callable; the patient_id if it returns nothing or raises), `vital_values` and `news2_points`: "Bed 4: breathing 26/min, 3 points". Points are left out when null (stale NEWS2). NEWS2 names drivers with 2 or more points (all scoring parts if none reach 2).

### Tuning the windows (training/tune_alerts.py, eICU)
- **Setup:** 1,945 stays (1,778 survivors, 167 non-survivors), first 24 h each, engine run once per stay with intake from age and sex (I9 cached), alert logic swept with every alert acknowledged 10 minutes later. Metrics: survivor new alerts per patient-hour; median minutes to the first alert for non-survivors.
- **Table (all four windows together):**

| window (min) | survivor alerts/h | warning | danger | NEWS2 | non-survivor median min to 1st | non-survivors alerted |
|---|---|---|---|---|---|---|
| 0 | 3.47 | 2.59 | 0.50 | 0.37 | 0 | 100% |
| 5 | 2.74 | 2.12 | 0.37 | 0.24 | 5 | 100% |
| 10 | 2.40 | 1.88 | 0.33 | 0.19 | 10 | 100% |
| 15 | 2.20 | 1.74 | 0.31 | 0.15 | 15 | 100% |

- **One at a time (others at 5/2/2):** warning window 0/5/10/15 gives 3.43/2.74/2.44/2.26 alerts/h; vital-danger window 2.90/2.74/2.72/2.70 (danger alerts fall 0.63 to 0.29 but nothing else moves); NEWS2 window 2.79/2.74/2.79/2.79 (NEWS2 alerts fall 0.37 to 0.15 as folding shifts alerts onto the vitals, so the total does not drop).
- **Chosen:** `warning_persisted_minutes` 10 (a warning is not an interruption; 10 saves about 11% over 5 for a median 5-minute later first alert, and 15 saves only 7% more). `vital_danger_minutes` 2, `news2_total_minutes` 2 and `trend_minutes` 5 unchanged: urgent alerts should not wait, and the trend trigger cannot be exercised on eICU.
- **Limits:** eICU rows are 5 minutes apart, so a window of 1 to 5 minutes behaves like 5 here; only 0 differs. Windows under 5 minutes (the urgent ones) cannot be resolved on this data and are set at C2 on the real strap. ICU patients are abnormal almost throughout (about 2.7 alerts per patient-hour at the defaults), so the absolute rates overstate a waiting room; use the table for the shape only. Revisit at C2 and C3.

## Simulation layer

### Fixed-length scripted runs replace event buttons
- **Options:** mix-and-match events over a live stream; one fixed run per sample patient.
- **Why a run per patient:** every run is identical each time (seeded), has an expected outcome to check, needs no handoff back to the strap, and a patient's history and story stay consistent. The cost is less flexibility on stage.
- **Revisit if:** the demo needs a mid-run intervention.

### Run mode replaces the strap, never blends
- **Options:** blend strap values into the calm phase; replace; a per-patient switch.
- **Why replace:** strap noise makes runs unrepeatable, and the wearer's age and body would not match the sample patient. Live mode keeps the hardware story. Ingest drops strap readings in run mode.

### Run length is one setting, scripts use fractions
- **Choice:** 10 minutes for now, so alerts and the 60-second median behave as they do live. Key times are fractions of the run, so a new length rescales all six scripts.
- **Known cost:** the personal baseline needs 10 clean minutes (`min_minutes`), so in a 10-minute run it forms as the run ends. Try 12 to 15 minutes if the demo should show it.

### End of run: stop sending, shown as a pause
- **Options:** hold the last values flat; stop; loop.
- **Why stop, with a run state:** the live window is a 60-second median, so after the data stops it empties within a minute, the dashboard blanks and the engine reads thin data as a lost signal. A run state (live, running, ended) on I13 lets ingest freeze its window and send no more minute rows, so the screen shows the last values with a "Run ended" label and alerts stay.

### Trend pre-roll: 120 minutes of starting values, through a separate engine entry
- **Options:** none; 30 minutes; 60 minutes; 120 minutes; 6 hours; a `history_only` flag on I6.
- **Why 120:** the fast model does not produce anything useful until about 15 minutes of history, which a 10-minute run never reaches, and the sepsis slow model needs 120 minutes (raised from 60 at the owner's direction). 120 minutes fills the fast model's 5/15/30-minute windows and the slow model's 1-hour window. Starting values, not calm ones, so at-risk and critical patients do not look like a sudden drop.
- **Why a separate entry, not a flag:** `seed_trend_history` makes "never reaches the personal baseline" structural, where a flag could be missed by one consumer, and it leaves I6 unchanged. The baseline's rule of learning nothing from a patient who arrives abnormal keeps working.
- **Cost:** the history is invented, and the slow model's 3 and 6 hour windows are only two thirds and one third full. The pitch says so. The length is one setting; 6 hours is 360 rows.

### In-process transport with a source argument
- **Options:** WebSocket client like the strap; in-process call.
- **Why in-process:** one code path and no socket to debug. Ingest's entry function takes a `source` argument so I1 stays untagged. Needs one server worker and no auto-reload while a run plays, and ticks scheduled from the run start so a run does not drift past its length.

### Six hand-written sample patients, no COPD
- **Options:** hand-written; random from NHANES-like rates; both.
- **Why hand-written:** each one shows something specific (a beta-blocker patient with a blunted heart rate rise, a patient already urgent on arrival, a blip the persistence window should absorb) and the demo script can rely on it.
- **Why no COPD:** I2 cannot say whether a clinician confirmed hypercapnic COPD, which NEWS2 scale 2 (88 to 92% SpO2) requires, so a COPD patient at 90% would read as danger.

### Checks done
- The NEWS2 total at 0, 30, 60 and 100% of each run, computed with the real scorer from the script values plus the patient's triage points, matches the target in the script (`tests/simulator/test_profiles.py`).

## B2 Allowed rules and adjuster test set

### Seven rules (models/rules.json)
- chemo_fever (temp high 38.3; IDSA febrile neutropenia, strong), suspected_infection (RR high 22; Sepsis-3 qSOFA, strong), opioid (RR low 10; ASA definition, medium), steroid_immunosuppressed (temp high 38.0; steroid fever blunting, medium), age65 (temp high 37.8; IDSA older adults, figure unconfirmed), beta_blocker (HR high 110; no numeric source), pregnancy (SBP high 160, HR high 120; MEOWS, weak). Sources are secondary summaries, not guideline texts; values are "proposed" and labels do not depend on them.
- **Rejected:** confirmed COPD (loosens SpO2), AF rate targets (no AF intake field), anticholinergics and diabetic neuropathy (no source), any SBP-only rule (SBP is one triage reading, never classified live). SNRI/tricyclic dropped: those drugs raise heart rate, so lowering the high edge is not supported.
- **age65 fires on age alone.** It was named age65_fever; renamed so the name matches the behaviour: every patient 65+ gets a 37.8 C temperature danger edge, which NEWS2 does not have. It is separate from the T2 temperature band, which only shifts the safe edge by about 0.02 C per decade.
- **Conflicts:** when two rules move the same edge, the stricter value wins.
- **Split by source:** structured rules (age, drug class, pregnant flag) are for code with fixed values; the LLM handles free-text facts (B1 finding).

### Test set: Claude-drafted, human sample check
- 100 synthetic cases (30 dev, 70 test; test never used in prompts), drafted and labeled by Claude (Sonnet) from a coverage grid: every rule fires in 5+ test and 2+ dev cases, near-misses per rule, and the training plan's hard cases (negation, past use, slang, brand names, misspellings, conflicts, nothing relevant, multi-rule, injection, missed lookups).
- **Deviation from the training plan** (one teammate labels, the other checks): Claude labeled. Checks: (1) a blind second Claude pass agreed 100/100 on rule and source, which we treat as weak evidence because the guide's examples mirror the cases and both passes were the same model family; quote spans differed in 27 of 45 text labels, so B3 should accept any quote in the complaint that covers the fact. (2) Nate labeled a random 20-case test sample blind: 15/18 answered agreed on rules (14/18 with source); every difference was reconciled in favour of the Claude label (a measured fever counts as suspected infection; age65 fires on age alone; the pregnant flag wins over text for source). On that basis the remaining 80 cases were accepted without individual checks.
- **Revisit if:** B3 scores look too good: add 15-20 fully human-written cases and report their score separately, and strip case-specific examples from the guide.

## S2 Ingest

### Wearable to patient: config default plus `assign()`
- **Options:** config default; explicit `assign()`; auto-assign unknown wearables; drop until intake.
- **Why:** both of the first two. One function is the I3 entry for the simulator and intake, and a config line (wearable 1 is `demo-001`) lets the strap work before intake exists. Unknown wearables stay dropped so wiring mistakes show up.

### Minutes start at the patient's stream start
- **Options:** from assignment or run start; wall-clock minutes.
- **Why:** a 10-minute run gives 10 whole rows instead of 11 with partial ends. The pre-roll still rounds to clock minutes, so there can be a gap of up to a minute between its last row and the first live row; recheck when T6 adds `seed_trend_history`. Cost: the rows do not match Tiger Data's clock buckets, so the live path does not depend on a database aggregate.

### A clean second needs contact and a heart rate
- **Options:** contact and hr; per-vital counts; any non-null vital.
- **Why:** one number, and it matches the I1 note that no-contact seconds are not clean. With the strap off, the simulated SpO2 and temperature also drop out, which reads as no patient on the device. The baseline discards minutes under 40 clean seconds, so this definition decides what it learns.

### Window rules: 5-sample minimum, wide bounds, 5 s simulator lifetime, arrival-time clock
- **Why:** a window of two or three seconds flickered NEWS2 at the start of a run, so a vital needs 5 clean samples. Bounds (hr 20-250, breathing 3-60, SpO2 50-100, temperature 30-45) drop only impossible values, so a true danger value always passes. A simulator value counts for 5 s so a stopped filler shows up. Readings are windowed on arrival time so a later move of the receiver to another machine cannot skew them; the source timestamp stays in the store.
- **Found in a live run:** tick jitter put 61 samples in a 60 s window (I13 allows 60), so the window holds at most 60; float medians such as 38.650000000000006 are rounded to 3 places.

### Ended run: frozen window, clock keeps moving, last minute closed
- **Why:** per-second consumers should not see a stale clock, and `run_state: ended` tells the dashboard it is a pause. Review found the last minute of every run was lost (the freeze came before the close), so the open minute is closed when the run ends.

### Bad messages keep the socket open
- Non-finite numbers become null before validation, so one bad field does not cost the reading. A message that still fails is logged and ignored; closing the socket would make the receiver back off for 1 to 15 s during a live demo.

### Storage: SQLite behind a queue
- One `events` table (kind, patient, time, source, JSON) written off the tick; a failed write is logged and never stops the loop. Tiger Data can be a second writer later.

## B3 Context adjuster

### One LLM call; code decides everything else
- **Options:** the four-step LLM chain (fact extractor, history reader, threshold proposer, reviewer); one call that proposes numbers; one call that reports facts only.
- **Chosen:** structured rules (age 65+, drug classes, pregnant flag) fire in code; one step-5-preview call reads the chief complaint for the six text-capable rules and returns rule id, short fact and quote, never a vital, bound or number. Values come from `models/rules.json`, merged in code (stricter wins on a shared edge, tighten-only against `ranges.DANGER`), output ordered by rules.json position.
- **Why:** B1 found temperature 0 still gave HR limits of 100, 110 and 130 for one intake, and calls take 6-45 s each, so four calls is too slow. Facts-only output cannot loosen a limit and leaves the model one small job.
- **Prompt:** built from each rule's `fires_when` and `does_not_fire` plus the guide's general rules; no case examples (B2 warning). Version `b3-0`, the first draft; it needed no tuning on dev.

### Quote check and validator
- Quotes are matched after lowercasing, straightening curly quotes and collapsing whitespace; otherwise word for word, and any matching span counts (B2). A proposal is dropped if its rule is off the text list, the quote is missing, the same rule already fired from structured fields, or it is a text pregnancy proposal while the pregnant flag is not null. Drops are counted by the score script, not stored in I15, so `quote_found` is true when text items exist and null otherwise.

### Cache and fallback
- Only validated text proposals are cached (`logs/`, gitignored), keyed on a hash of the rendered messages, prompt version, model settings (model, temperature, max_tokens, reasoning_effort) and reply schema; structured rules are recomputed on every call. A failed or skipped call (empty chief complaint) returns structured rules only, marked "structured only" in I15 `model`, and is never cached. A bad cache entry counts as a miss; cache and log write failures are ignored. The score script runs with cache and log off.

### Scores (prompt b3-0, step-5-preview, cache off)
- **Structured only, dev:** precision 1.000, recall 0.562, exact 18/30 (the rest needs the text call).
- **Dev, live:** precision 1.000, recall 1.000, exact 30/30, in every one of the repeated runs. Stability over 3 runs: 22/30 cases byte-identical in facts and quotes (the model picks different quote spans), 30/30 identical in fired rules and I5, which is what the engine sees.
- **Test, live, scored once:** precision 1.000, recall 0.982, exact 69/70, 55 true positives, 0 false positives, 1 miss, 1 proposal dropped (its quote was not in the complaint, so the validator removed it), 0 loosening violations, latency median 4.2 s, slowest 77.6 s (one slow call; the others were under 30 s on dev).
- **Reading the score:** the labels are weak evidence (Claude-drafted, 20-case human sample) and the labeling guide's wording is close to the prompt's, so the near-perfect score is likely optimistic. **Revisit if:** the 15-20 fully human-written cases from B2 "Revisit if" score noticeably lower.

### Known gaps
- Sample patients carry no `drug_classes` until the S5 lookup exists, and the guide never fires from the medication list alone, so U1 and C1 lose beta_blocker for now. chemo_fever is missed for C2 (capecitabine, no mention of chemo in the complaint); that matches the guide.

## T6 Fast trend model (training/, backend/risk_engine/fast_features.py, fast_model.py)

### MIMIC-III sample: seeded random, 300 patients, up to 2 records each, one-per-second records kept
- **Speed:** 10 records (3.7 MB) took 41 s at about 90 KB/s with 10 workers. The full pull ran 24 workers (about 190-250 KB/s overall, 19% of fetches timing out at 60 s, retried by rerun): 375 of 450 records and 781 MB in 56 min, then a second pass with 8 workers added about 110 MB before it was stopped. 448 complete records (from 300 sampled patients) were used; 2 partial files were ignored. Once-a-second records were not capped (222 of 634 segments).
- **Sample is seeded** (`--seed 0`), so the same patients come back on a rerun.

### Cleaning filters and counts (448 records read)
- 11 records lacked HR, breathing or SpO2 and were skipped; 228 gap splits (> 10 min with none of the three vitals); 23 segments under 50 minutes dropped; physiologic limits reused from `build_eicu_fixtures.LIMITS` (zeros from probe-off fall outside and become null; PULSE fills only where HR is null); 2,228 SpO2 minutes nulled by the artifact filter (a fall of more than 10 points from the last accepted value, for at most 4 consecutive minutes, so a sustained low is kept).
- **Neonate / mostly-in-danger filter:** first-hour median HR > 130 or breathing > 30, or > 40% of minutes in danger. It dropped 119 of 634 segments (281,901 of 1,263,308 minutes). It also removes some very sick adults; accepted, because the label is undefined for people who are already in danger.
- **Kept:** 515 segments, 259 patients, 981,407 minutes. One-second records collapse to a minute median needing >= 30 of 60 samples.
- **Source-rate check** (kept minutes): once-a-second vs once-a-minute records have similar medians (HR 81 vs 84, breathing 18 vs 18, SpO2 98 vs 98) and event rates (12.4 vs 12.9 per 100 h), so the two are pooled.

### Label (15 minutes ahead, NEWS2 score 3)
- As in the plan: danger = HR <= 40 or >= 131, breathing <= 8 or >= 25, SpO2 <= 91 (the engine's own bands); an event is 5 consecutive observed minutes, a null minute breaks the run; onset within 15 minutes; negatives need 15 observed minutes per vital in the next 20; in-event and 30 minutes after excluded; rows start at the 15th observed minute.
- **Result:** 658,999 labeled rows, 22,434 positives (3.4%), 2,064 fresh events. Events by vital: breathing 1,513, SpO2 557, HR 53 (HR positives come from only 17 patients). The model is therefore mostly a breathing and SpO2 model; HR is too rare to say anything about.
- **Eyeballed 20 random positives:** the SpO2 ones look right (a slide or dips to 90-91 sustained 5+ minutes); most breathing ones are patients hovering at 22-26/min who tip over 25 for 5 minutes, i.e. real by the label but near-threshold noise; two are low-breathing runs (<= 8). One positive's displayed window was mostly null for SpO2 (valid because other vitals were observed).

### Features: 60 per minute, two dropped for train/serve parity
- Median, slope, spread, min, max over 5/15/30 min by timestamp, plus distance of the median to each danger edge; a window with < 60% of its minutes observed is NaN.
- **Dropped:** change versus the first 15 minutes (means "since arrival" live, "since some gap" in MIMIC) and missing-data fractions (live SpO2 is simulated and never missing).

### Baselines and ship rule
- **Distance:** closest 5-min median to any edge divided by max(15-min spread, floor 5/1/1 for HR/breathing/SpO2), max over vitals and edges. **Extrapolation:** 5-min median plus 15 x the 15-min slope, overshoot past an edge in raw units, max over vitals.
- **Setup:** 80% / 20% patient split (207 / 52 patients, seed 0), 5-fold patient-grouped CV for LightGBM (patient-weighted, scale_pos_weight, early stopping on AUPRC), cutoffs matched on training patients to partial-NEWS2 >= 5 alerts per monitored hour (0.716/h; held-out 0.655/h; SBP held 30 min from the last NBP). Alerts have a 15-minute refractory period.
- **Held-out (388 events):**

| Method | Alerts/h | Minutes of warning | Share detected | AUPRC |
| --- | --- | --- | --- | --- |
| LightGBM | 0.95 | 19.5 [15.2, 23.2] | 0.48 [0.38, 0.56] | 0.158 |
| Distance | 0.69 | 26.6 [23.8, 29.0] | 0.76 [0.70, 0.80] | 0.107 |
| Extrapolation | 0.71 | 23.5 [20.9, 26.1] | 0.73 [0.67, 0.78] | 0.062 |
| Hourly nurse recheck | 1.0 | 0 | 0.16 | |

- **Ships: the distance baseline** (better of the two on training patients). LightGBM has the best AUPRC (it ranks all minutes better) but alerts more often on held-out than its OOF-matched cutoff promised and warns less at the same budget; the paired bootstrap says it is worse (warning -11 to -3 min, detected -0.35 to -0.21). Distance vs extrapolation overlap on held-out, so that choice is close.
- **Cutoff:** distance score -0.47 (about half a spread inside the edge), stored as `trend.fast_warning_cutoff`. I9 `trend_prob_fast` carries the score, not a probability. At stricter budgets (0.25/h and 0.5/h) distance still warns 9.6 and 18.7 min on average.
- **Warning only**, raise-only, reasons from the driving vital and edge ("SpO2 falling" vs "SpO2 near danger").

### Known skews
- Strap breathing rate is not the impedance RESP in MIMIC; SpO2 is simulated in the demo; the label uses fixed NEWS2 limits while live levels use personal ranges; ICU patients sit near edges so the matched cutoff is tight; the eICU second check from section 4b is dropped (5-minute spacing cannot feed timestamp windows).
- **Demo consequence:** the distance baseline ignores slope, so on the gradual demo slide (`fixtures/fast_spo2_drop_i6.jsonl`, 97 to 90 over 20 minutes) the score reaches the cutoff only about at SpO2 91, and the trend tier never appears before the danger level. Extrapolation (cutoff 3.26) would warn near SpO2 94. Left as shipped per the rule; revisit at C3.

## Stated limits
- NEWS2 was validated mainly on admitted patients; we use it in a waiting room.
- NHANES pulse is seated and resting; anxious waiting patients may run above the 90 bpm cap and show warning (check at C2; the fix would be a config offset).
- eICU is ICU data in 5-minute aggregates, so tuning there checks mechanics, not waiting-room performance.
