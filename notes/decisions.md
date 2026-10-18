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

## Stated limits
- NEWS2 was validated mainly on admitted patients; we use it in a waiting room.
- NHANES pulse is seated and resting; anxious waiting patients may run above the 90 bpm cap and show warning (check at C2; the fix would be a config offset).
- eICU is ICU data in 5-minute aggregates, so tuning there checks mechanics, not waiting-room performance.
