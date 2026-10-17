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
- Skipped-by-pattern, refused (7) and don't-know (9) answers count as "no"; ages 18-19 have no MCQ items and count as "no"; age is top-coded at 80. Without the skip rule the BP-medication-style items were blank for most adults and the regression would have silently dropped them.

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
- **Why:** with n0 = 10 a patient whose normal HR is 85 (population 70, own spread 3) got a band of about 69-81 and their normal showed as warning for the whole stay. In the conjugate model n0 should be own-variance / between-person-variance; with sigma = own spread and tau = population band width / 3.92 this is about 0.1-0.2 for HR, so n0 is that ratio bounded to 0.5-5.
- **Revisit if:** replay shows the blend trusting too little or too much data.

### Band shape: contains the patient's median, k = 2.5, spread floors, minimum widths
- **Why:** the band is for single minutes, not the mean. Plus/minus 1.96 sigma from 5 minutes flags about 95% of normal patients within an hour, and a median absolute deviation from 5 points underestimates spread. So: half-width = k * sigma * sqrt(1 + 1/(n0 + n)) with k = 2.5, spread floors (HR 5 bpm, breathing 2/min), minimum widths (HR 16, breathing 6), 10 minutes minimum before any personal band, and the band is widened to include the patient's median. The band is clipped to the population band (no sliding), so it can only narrow.
- **Finding from tests:** with the breathing floor at 2, the band is about 10 wide, wider than the 8-wide population range, so breathing never narrows. The floor needs tuning (T3b).
- **Revisit if:** tuning on eICU (5-minute aggregates, so smaller spread than live) or the strap at C2 shows constant warnings or none.

### Arrival check uses NEWS2 points
- **Options:** population safe band; NEWS2 points; danger only.
- **Why:** pain or anxiety raises waiting-room HR, and a population-band check would skip most real patients. A vital that scores any NEWS2 points in the first 3 minutes is skipped (an anxious HR of 88 still learns; 95 does not). A patient whose own median is outside the population band is also not personalized.

### Freeze after 30 minutes
- Learning forever would slowly absorb a deterioration. After the window the band stops moving but readings are still classified, so a later slow drift inside the population range still reaches warning (synthetic wearer: band 59-85 frozen, drift reaches warning at 87).

### Windows count time, not rows
- eICU rows are 5 minutes, live rows 1 minute. Windows and n use `minute_ts` so both behave alike.

### Chosen start values: k = 2.5, floor multiplier 1.0 (HR floor 5, breathing 2; min widths 16 and 6)
- **Evidence** (`training/tune_baseline.py`, first 4 hours of 1,945 eICU stays: 1,778 survivors, 167 non-survivors): relative to population bands only, k=2.5 / x1.0 raises the survivor flag rate to 1.04x and the non-survivor flag share to 1.01x. Looser settings (k=3.0 with floor x1.5) do almost nothing (1.00x) and never personalize breathing; tighter ones (k=2.0 / x0.5) raise survivor flags to 1.18x. Under the chosen setting a personal HR band forms in 54% of survivor stays and breathing in 33%.
- **What this does and does not show:** about 95% of ICU stays are already in warning or danger on HR or breathing under the plain NEWS2 bands, so false-alarm rates and time-to-first-flag cannot separate the settings (median time to first flag is 0 everywhere). The sweep confirms the mechanics and that personalization adds few flags; it cannot show the benefit. The synthetic wearer replay and the strap at C2 are the real tests.
- **Revisit if:** the strap at C2 shows frequent warnings in a calm wearer (raise k or the floors) or misses a real drift (lower them).

### Checks done
- A raw eICU row (stay 197617, offset 4064: HR 117, RR 48, SpO2 93, temp 37.7) scored by hand from the NEWS2 chart (2, 3, 2, 0 points) matches the engine.
- One survivor who starts normal (stay 1048833) was added to the fixtures so the personal band has a real stay to learn from: it personalizes at minute 18 and has 10 warning rows of 220. The synthetic wearer (fixtures/wearer_drift_i6.jsonl) personalizes at 15 minutes, freezes at 30, and the later rise reaches warning at 87 bpm.

## Stated limits
- NEWS2 was validated mainly on admitted patients; we use it in a waiting room.
- NHANES pulse is seated and resting; anxious waiting patients may run above the 90 bpm cap and show warning (check at C2; the fix would be a config offset).
- eICU is ICU data in 5-minute aggregates, so tuning there checks mechanics, not waiting-room performance.
