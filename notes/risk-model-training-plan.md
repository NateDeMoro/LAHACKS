# Risk Model Training Plan

Oct 17, 2026 · @Nate

How every part of the risk layer is built, from data to evaluation. Only the fast trend model is trained in the machine-learning sense; the baseline ranges are fit from population data, the personal baseline and alert logic are tuned, and the context adjuster is evaluated against labeled examples.

## At a glance

Five pieces, four build methods. Each row is detailed in its own section below.

| Component | Build method | Data | Output |
| --- | --- | --- | --- |
| Baseline ranges | Fit (quantile regression) + published reference ranges + guideline rules | NHANES 2017–Mar 2020; NEWS2; reference studies | Safe / warning / danger band per vital, per patient |
| Context adjuster | LLM extraction, evaluated against labeled examples (optional fine-tune) | Hand-labeled intake texts; MIMIC-IV-ED demo chief complaints | Danger-threshold tightenings (I5); facts and quotes logged separately (I15) |
| Personal baseline | Bayesian update, one tuned setting | eICU demo (tuning and check) | Bands narrowed toward the patient's own readings |
| Trend model | One trained classifier, fast (15 min ahead); the slow sepsis model is future work (section 4) | MIMIC-III waveform vitals; eICU demo as a mechanics check | Warning tier when a vital is likely to enter the danger range within 15 min, + a reason |
| Signal quality, breathing rate, alert logic | Rules with tuned thresholds | eICU replay | Clean vitals, breathing rate, alert decisions |

## 1. Baseline ranges

Heart rate and blood pressure bands are fit on NHANES; SpO2, breathing rate and temperature come from published references, because no open population dataset links them to patient features. The danger tier starts at NEWS2 for every vital; the context adjuster (section 2) may tighten it.

### How the three bands are defined

- **Safe:** inside the range where 95% of similar people sit at rest (the patient's predicted 2.5th–97.5th percentile).
- **Danger:** a NEWS2 single-parameter score of 3, which by itself triggers urgent clinical review ([RCN NEWS2 card](https://startingout.rcn.org.uk/Develop/Nursing-Essentials-Crib-Cards/NEWS2); [NHS Scotland guideline](https://rightdecisions.scot.nhs.uk/media/vhcccgq2/news2-guideline-no-fp.pdf)).
- **Warning:** everything between the two.

| Vital | NEWS2 score-3 (danger) | NEWS2 score-0 range |
| --- | --- | --- |
| Heart rate (bpm) | ≤40 or ≥131 | 51–90 |
| Breathing rate (/min) | ≤8 or ≥25 | 12–20 |
| SpO2, scale 1 (%) | ≤91 | ≥96 |
| Systolic BP (mmHg) | ≤90 or ≥220 | 111–219 |
| Temperature (°C) | ≤35.0 | 36.1–38.0 |

Source: [MDCalc NEWS2](https://www.mdcalc.com/calc/10083/national-early-warning-score-news-2) and the [RCP NEWS2 report](https://www.rcp.ac.uk/media/a4ibkkbf/news2-final-report_0_0.pdf). An aggregate NEWS2 of 5 or more is also an urgent threshold; the live monitor uses it (section 4).

Live, the other NEWS2 parts come from intake: alertness entered by the nurse, the on-oxygen flag, and systolic BP from the single triage reading (never repeated), which keeps its points for the whole wait. The NHANES fit and personal baseline only move the safe band. The danger values move only through the context adjuster, and only inward, so danger is reached sooner, never later. NEWS2 was validated mainly on admitted patients, so using it in a waiting room is an assumption we state.

### Heart rate and blood pressure: fit on NHANES

**Data.** NHANES 2017–March 2020 pre-pandemic files, all open XPT downloads from the [CDC 2017 data page](https://wwwn.cdc.gov/nchs/nhanes/search/datapage.aspx?Component=Examination&CycleBeginYear=2017): P\_DEMO (age, sex, pregnancy, exam weights), P\_BPXO (three automated BP and pulse readings), P\_BMX (height, weight, BMI), P\_DIQ (diabetes), P\_MCQ (asthma, COPD), P\_BPQ (hypertension), P\_RXQ\_RX (prescription drug IDs), joined to RXQ\_DRUG for drug classes ([RXQ\_DRUG doc](https://wwwn.cdc.gov/Nchs/Data/Nhanes/Public/1988/DataFiles/RXQ_DRUG.htm)). We use this cycle, not 2021–23, because the newest prescription file has only yes/no medication flags and no drug names (checked by download).

**Cohort.** Adults 18+ with at least two valid pulse readings. Pregnant participants are excluded and handled by a rule instead.

**Targets.** Mean of the three automated pulse readings; mean systolic and diastolic BP.

**Features.** Age, sex (male or female, as NHANES records it), BMI, on BP medication, drug-class flags (beta-blockers, SSRIs, SNRIs, tricyclics, others as sample size allows), and every condition with enough participants to fit a shift: hypertension, asthma, cancer, diabetes, thyroid disease, COPD, liver disease, heart disease (coronary heart disease, angina and heart attack combined), stroke, heart failure. Kidney disease is pending a check of its NHANES file.

**Condition counts** (adults with a pulse reading, NHANES 2021–23, 6,123 people; checked by download): hypertension 2,241, asthma 1,127, cancer 881, diabetes 842, thyroid 812, COPD 432, liver 348, coronary heart disease 312, stroke 267, heart attack 253, heart failure 244, angina 131. The 2017–2020 cycle adds roughly as many again. Each condition is a shift term in one pooled model, so a few hundred people is enough.

**Model.**

1. Linear quantile regression at the 2.5th, 50th and 97.5th percentiles first. Each coefficient is directly a per-feature shift, which becomes the explanation on the dashboard ("range lowered 4 bpm: beta-blocker").
2. If it fits poorly, LightGBM with `objective='quantile'` and `alpha` set to each percentile, one model per percentile ([LightGBM parameters](https://lightgbm.readthedocs.io/en/latest/Parameters.html)). `monotone_constraints` can force sensible directions where the evidence is clear.
3. Sort the three predictions so the bands never cross.

**Survey weights.** NHANES oversamples some groups. For population percentiles use the exam weight WTMECPRP; for a model conditioned on features we fit unweighted and say so.

**Validation.** Hold out 20% of participants. The key check is coverage: about 95% of held-out people should fall inside their own predicted band, overall and within subgroups (beta-blocker users, BMI 40+, age 70+). Subgroup coverage is what shows personalization works.

**Early signal already measured** (unweighted, adults, P\_ files): median resting pulse 65.7 bpm on beta-blockers vs 69.8 off them (n=936 on); 69 bpm at BMI ≤25 vs 74.8 at BMI ≥40. Percentiles by age and sex, men 18–29: 53 / 69 / 91 (5th / 50th / 95th); men 70–80: 49 / 64 / 86.

### SpO2, breathing rate and temperature: published references

NHANES has no SpO2, breathing-rate or body-temperature measurements in any 1999–2023 examination file checked ([2017 file list](https://wwwn.cdc.gov/nchs/nhanes/search/datapage.aspx?Component=Examination&CycleBeginYear=2017); [2021 file list](https://wwwn.cdc.gov/nchs/nhanes/search/datapage.aspx?Component=Examination&CycleBeginYear=2021)).

| Vital | Safe band and adjustments | Source |
| --- | --- | --- |
| Temperature | Mean 36.6 °C, 95% range 35.7–37.3 °C in 35,488 adults; falls about 0.02 °C per decade of age; measured factors explain only 8% of variation | [Obermeyer 2017, BMJ](https://www.bmj.com/content/359/bmj.j5468.long) |
| SpO2 | Daytime 96.2 ± 1.4% in 33,080 wearable users; ≤92% in 0.1% of people under 60 vs 1.9% at 70+; BMI ≥30 lowers SpO2 | [Apple Heart & Movement Study 2023](https://pmc.ncbi.nlm.nih.gov/articles/PMC10374661); [Vold 2015, Tromsø](https://bmcpulmmed.biomedcentral.com/articles/10.1186/s12890-015-0003-5) |
| Breathing rate | No covariate-adjusted adult reference found; use NEWS2 score-0 range 12–20 as the safe band | [RCP NEWS2 report](https://www.rcp.ac.uk/media/a4ibkkbf/news2-final-report_0_0.pdf) |

### Guideline adjustments (candidate rules)

Candidates considered for the context adjuster's rule list (section 2). The final seven rules, with sources, are in `models/rules.json` (B2; reasons in [decisions.md](decisions.md)).

| Factor | Adjustment | Source |
| --- | --- | --- |
| Confirmed hypercapnic COPD | SpO2 target 88–92% (NEWS2 scale 2); only when a clinician has confirmed it, never from self-report or the LLM | [RCP NEWS2 report](https://www.rcp.ac.uk/media/a4ibkkbf/news2-final-report_0_0.pdf) |
| Beta-blocker | Lower the high-HR warning edge; tachycardia is an unreliable sign on these drugs | [J Intensive Care 2021](https://doaj.org/article/534b643510c745418abca8a5271d43d8) |
| Age 65+ / frail | Fever = single reading >37.8 °C, repeated >37.2 °C, or a rise >1.1 °C over baseline | [IDSA guideline, High 2009](https://pmc.ncbi.nlm.nih.gov/articles/PMC7166905) |
| Antidepressants | Tricyclics and SNRIs raise HR; SSRIs slightly lower it | [Licht, NESDA](https://pmc.ncbi.nlm.nih.gov/articles/PMC3442343) |
| Pregnancy | HR rises from about 79 to 87 bpm between weeks 10 and 40; SBP 110 to 116 | [Loerup 2019, BMC Med](https://bmcmedicine.biomedcentral.com/track/pdf/10.1186/s12916-019-1399-1) |

## 2. Context adjuster

The LLM is not trained on outcomes; it is prompted to extract facts into a fixed format, and we measure how accurately it does that on a labeled test set we write ourselves. Its only effect on scoring is to tighten danger thresholds, using rules from an allowed list (decided later; candidates in section 1). Contracts: I4 in, I5 and I15 out ([component-map.md](component-map.md)).

### What it is allowed to output

- **Inputs:** the full patient context (I4), including the chief complaint.
- **Adjustments (I5, to the risk engine):** a list of {rule, vital, low or high bound, new danger threshold}. Tighten only: a high bound can only move down, a low bound only up. A code validator checks every proposal against the allowed rules, vitals and edges, and values come from rules.json (the model never picks a number); anything that does not tighten is dropped.
- **Evidence (I15, to the evaluation log only):** the fact and the exact quote behind each adjustment. Code checks that the quote appears word-for-word in the chief complaint; an adjustment without a matching quote is dropped. The risk engine never reads the evidence.
- **No red flags.** Triage acuity is the nurse's ESI level; the adjuster only changes thresholds.
- **Pipeline:** structured rules fire in code (age, drug classes, pregnant flag); one LLM call reads the chief complaint for facts and quotes; a code validator and a rules.json merge produce I5 and I15 ([stack-reference.md](stack-reference.md), decisions.md B3). This replaced the four-step LLM chain.

### Medication lookup

Mapping a drug name to a drug class is deterministic (the S5 intake lookup does it from a small hardcoded table in `backend/intake/lookup.py`; the adjuster only reads `drug_classes`), and the LLM covers unmatched medications named in the complaint, instead of the full NHANES RXQ\_DRUG list (1,551 drugs with Multum classes, [RXQ\_DRUG doc](https://wwwn.cdc.gov/Nchs/Data/Nhanes/Public/1988/DataFiles/RXQ_DRUG.htm)). The demo needs only six classes and a few dozen names; the table covers every medication in the B2 test set, the sample patients and the wearer fixture, and misspellings stay unmatched on purpose. The LLM's job is the part a lookup can't do: slang, brand names, misspellings and phrases like "something for my nerves."

### Test set

No open dataset has realistic free-text intake. The MIMIC-IV-ED demo's chief complaints are short codes such as "SOB" and "HEAD BLEED" (222 triage rows, checked by download; [dataset page](https://physionet.org/content/mimic-iv-ed-demo/2.2/)). So we write the test set:

1. About 100 short intake texts, covering every allowed rule at least five times.
2. Hard cases on purpose: negation ("I stopped my beta blockers last month"), slang ("weed"), brand names, two conflicting facts, nothing relevant at all.
3. Each text labeled with the expected output by one teammate and checked by the other; disagreements resolved before testing. _As built (B2): Claude drafted and labeled 100 cases (30 dev, 70 test) and a 20-case human blind sample checked them; see [decisions.md](decisions.md) and [adjuster-labeling-guide.md](adjuster-labeling-guide.md)._
4. Use the MIMIC chief-complaint codes only as seeds for realistic complaint topics.

### Metrics

| Metric | Target |
| --- | --- |
| Fact precision and recall | Report both; precision matters because false facts tighten thresholds for no reason |
| Adjustment exact match | Share of texts where the full set of adjustments is right |
| Quote validity | 100% after the code check, by construction |
| Loosening violations | Zero, enforced by the code validator |

### Model choice

- **Default:** StepFun step-5-preview through the OpenAI SDK (`backend/llm.py`), with strict JSON Schema output, low reasoning effort and temperature 0 (values still vary between runs); the StepFun challenge requires the app to call it at runtime.
- **Considered:** Jev (TypeSafe AI), a decision model that answers fixed-choice questions with a probability. A fit for picking rules, but it can't return quotes and access was unclear; optional.
- **Optional fine-tune (veri.studio challenge):** fine-tune a small open model on extra labeled examples and compare it with StepFun on the same held-out texts. Veri's challenge asks for exactly this before-vs-after comparison ([veri.studio](https://www.veri.studio/lahacks)).

Keep test texts out of any prompt examples or fine-tuning data, or the scores will be inflated.

## 3. Personal baseline

The baseline is not trained; it is a standard Bayesian update with one setting to tune. It exists because patient features explain little of individual variation: in 92,457 wearable users, resting-HR baselines ranged 40–109 bpm and age, sex, BMI and sleep explained under 10% of the differences ([Quer 2020](https://pmc.ncbi.nlm.nih.gov/articles/PMC7001906)); for temperature, measured factors explained 8% ([Obermeyer 2017](https://www.bmj.com/content/359/bmj.j5468.long)).

### The update

For each vital, the patient's true resting level starts as the section-1 prediction and moves toward their own readings as they accumulate (normal-normal conjugate update; [Murphy, conjugate Gaussian analysis](https://www.cs.ubc.ca/~murphyk/Papers/bayesGauss.pdf)):

```latex
\hat{\mu}_n = \frac{n_0\,\mu_0 + n\,\bar{x}_n}{n_0 + n}
```

- μ₀ is the predicted median from section 1; x̄ₙ is the median of the patient's clean one-minute readings so far; n is the number of those minutes.
- n₀ is the one tuned setting: how many minutes of the patient's own data it takes to count as much as the population guess. With n₀ = 10, the patient's data carries half the weight after 10 clean minutes and three quarters after 30.
- Use one-minute medians, not raw samples. Consecutive heartbeats are strongly correlated, so counting every sample would make the update far too confident.
- The personal safe band is the updated level plus or minus the patient's own minute-to-minute spread, estimated from the same minutes with a robust measure (median absolute deviation).

### Safety catch

A patient who arrives already deteriorating would teach the system that abnormal is their normal. Three rules prevent that:

1. The personal safe band may only be narrower than the population safe band, never wider or shifted outside it.
2. The personal baseline never moves the danger tier; only the context adjuster can, and only inward.
3. If the first readings already sit in warning or danger, no baseline is learned; the patient is flagged instead.

### Tuning and checking n₀

_Superseded: n₀ is now derived from the data and bounded, and tuning targets k and the spread floors. See [decisions.md](decisions.md) (T3 Personal baseline)._

- **Data:** eICU demo, 5-minute vitals for about 2,500 ICU stays with hospital-death labels ([dataset](https://physionet.org/content/eicu-crd-demo/2.0.1/)); vitals present for 94% of stays, checked by download.
- **Procedure:** replay each stay through the update with n₀ from 3 to 30. For each value, count warnings per patient-hour among survivors (false-alarm proxy) and how often patients who died were flagged at any point.
- **Choice:** the smallest n₀ that keeps survivor warnings near the population-band rate while not reducing flags in non-survivors.
- **Caveat:** eICU patients are already sick, so this is a sanity check on the mechanics, not proof it works in a waiting room.

## 4. Slow trend model (hours ahead) — future work, not built

Dropped for the hackathon (T5): its useful change inputs need 90–120 minutes of data, while the median US ED wait to see a clinician is under 30 minutes, so it would stay silent for most patients (see decisions.md). Kept as the design for long-wait EDs. Sepsis is presented as one cause of deterioration that NEWS2, personal ranges and the fast model catch.

The design: a classifier that reads the last few hours of a patient's vitals and predicts whether they are heading toward sepsis, trained on PhysioNet 2019 and checked on eICU.

### Data and label

- **PhysioNet/CinC 2019 Sepsis Challenge:** 40,336 ICU patients, one row per hour, with 8 vitals (HR, O2Sat, Temp, SBP, MAP, DBP, Resp, EtCO2), 26 lab values and age, sex, unit and hours since admission ([dataset page](https://physionet.org/content/challenge-2019/1.0.0/)). Distributed as training set A (20,336) and set B (20,000).
- **Label:** SepsisLabel, defined by Sepsis-3 (a 2-point SOFA rise plus suspected infection) and already shifted 6 hours earlier than clinical onset, so a positive row means "sepsis within about 6 hours or already present" (same page). Sepsis patients are a minority: 28 of a 300-patient sample (9%), checked by download.
- **Provenance:** the challenge drew on ICU patients from three hospital systems, two of them public; 104 teams made 853 submissions ([Reyna 2020, Crit Care Med](https://pmc.ncbi.nlm.nih.gov/articles/PMC6964870/)).

### Inputs: only what the waiting room will have

Labs are dropped; nobody draws blood in the waiting room. Features use heart rate and breathing rate (measured live), SpO2 and temperature (simulated in the demo, real in training), triage systolic BP held constant, age and sex.

For each vital, computed at every hour over windows of 1, 3 and 6 hours:

- last value, mean, minimum and maximum
- slope (least-squares line over the window)
- change since the patient's first recorded hour
- hours since the last real measurement, plus a missing flag; temperature is present in only 34% of rows in our sample, so missingness carries information

Across vitals: NEWS2 computed from the available vitals (consciousness assumed alert), its change over 3 hours, and the number of vitals moving in a worsening direction together. Plus hours since arrival.

### Model

1. **Baseline:** logistic regression on the same features, to know what the simple version achieves.
2. **Main model:** LightGBM binary classifier. Class imbalance handled with `scale_pos_weight` ([LightGBM parameters](https://lightgbm.readthedocs.io/en/latest/Parameters.html)). Per-feature contributions for each prediction (`pred_contrib=True`) become the dashboard's one-line reason.
3. **Thresholds:** the output probability is mapped to warning and danger by choosing cut-offs that fix the alert rate (below), not by a default of 0.5.

### Splits

- Split by patient, never by row; rows from one patient on both sides lets the model memorize that patient.
- Tune on set A with 5-fold cross-validation grouped by patient; test once on set B. Because the two public sets come from different source data, this approximates testing at a new hospital.

### Evaluation on set B

| Metric | What it shows |
| --- | --- |
| AUROC and AUPRC, hour level | Ranking ability; AUPRC is the honest one when positives are rare |
| Official challenge utility score | Comparable to the published challenge; rewards predictions from 12 h before to 3 h after onset and heavily penalizes misses ([dataset page](https://physionet.org/content/challenge-2019/1.0.0/)) |
| Hours of warning at matched alert rate | Our headline: fix alerts per patient-hour equal to NEWS2 ≥5, then compare how many hours before onset each first fires |

**Check on eICU.** The 2019 data is hourly, so it can't show the value of checking more often. eICU's 5-minute vitals can: compare the same rule evaluated every 5 minutes against every 60 minutes, using hospital death as the outcome. That is the direct analogue of the SNAP40 finding that continuous monitoring caught deterioration a median of 65 minutes earlier than manual vital signs in a subgroup of 31 ED patients ([SNAP40-ED study](https://www.pagepressjournals.org/ecj/article/view/9711)).

### Output

Every minute: a probability (0–1) of sepsis within about 6 hours, plus the top 3 feature contributions as the one-line reason. Saved as a LightGBM model file; cutoffs in config.json (I7). Training with `scale_pos_weight` inflates raw probabilities: they rank correctly but are not real percentages. Compare them only against cutoffs, or add a calibration step fitted on held-out patients if the dashboard shows percentages.

### Running it live

The live stream is collapsed into one-minute medians, then into the same hourly windows the model was trained on, and the model is re-run every minute on the rolling windows. Early in a patient's wait there is little history, so predictions lean on current levels; we show that uncertainty to the nurse rather than hide it.

## 4b. Fast trend model (minutes ahead) — built

The slow model can't catch deterioration that shows up within 15 minutes, and hourly data can't be stretched to do it. So the fast model is trained on minute-level data and forecasts each vital over the next 15 minutes. It is the only trend model we build. Section 4 (slow model) stays future work. Numbers and decisions: decisions.md, "T6 Fast trend model".

### Data

- **MIMIC-III Waveform Database, matched subset** (open access, ODbL; [dataset page](https://physionet.org/content/mimic3wdb-matched/1.0/)): only the periodic numerics records (HR, SpO2, breathing rate), fetched with `training/fetch_mimic_numerics.py` (seeded random patient sample, up to 2 records each; the server is slow and has no S3 mirror, so retries and `--exclude-dir` for later batches). First sample: 300 patients, 448 records read. Second batch (`mimic3wdb_batch2`, 600 patients, seed 1, excluding the first 300) is downloading and serves as the fresh test, then as extra training data on retrain.
- **Cleaning** (`training/mimic_numerics.py`): physiologic limits (probe-off zeros become null); a gap of more than 10 minutes splits a segment; segments under 50 minutes dropped; an SpO2 artifact filter (a fall of more than 10 points, lasting 4 minutes or less); one-second records collapse to minute medians. Neonate and mostly-in-danger filter: first-hour median HR above 130 or breathing above 30, or more than 40% of minutes in danger. Kept 515 segments from 259 patients (981,407 minutes).
- **No demographics or outcomes** (that needs credentialed MIMIC access), so the model reads vitals only; personalization comes from sections 1 and 3. The eICU second check was dropped (5-minute spacing cannot feed timestamp windows).

### Targets and inputs

- **Targets** (`training/fast_forecast.py`): at each minute where the patient is not in danger, the lowest SpO2, the lowest and highest breathing rate, and the lowest and highest HR over the next 15 minutes (five targets). A row is skipped when the window leaves the segment or fewer than 12 of the 15 minutes are observed.
- **Inputs** (`backend/risk_engine/fast_features.py`, shared by training and live, so they cannot drift): 60 features per minute from HR, breathing and SpO2 only (BP is not streamed): median, slope, spread, min and max over 5, 15 and 30 minutes, plus the distance of the median to each danger edge; a window under 60% observed is missing.

### Model and alert rule

- **Model:** LightGBM regression per target, predicting the change from the current 5-minute median; for each target a median model and a cautious quantile model (10% for lowest, 90% for highest). Split by patient (207 train / 52 held-out, seed 0); patient-weighted; 4-config search by patient-grouped 5-fold CV on pinball loss with early stopping. Median models are for evaluation only; the engine loads the five cautious ones.
- **Alert rule:** the score is how far the cautious forecast lands past the danger edge (NEWS2 score-3 limit), in points; the maximum over targets. A warning trend tier is raised when the score reaches the cutoff, which was matched on training patients to the alert rate of partial NEWS2 of 5 or more (0.716/h), giving 4.856. Warning only, never lowers a level, only while no vital is in danger and after 15 clean minutes. Reason: "SpO2 may reach 90% within 15 min".

### Evaluation

- **Forecast accuracy** against two baselines, the no-change forecast and the straight 15-minute-slope line, plus calibration (share of outcomes beyond the cautious forecast, nominal 10%).
- **As an alarm**, against Rule 1 (distance to the edge, in spreads), Rule 2 (slope extrapolation), a logistic regression over the rules, a LightGBM yes/no classifier and a nurse recheck every 60 minutes: alerts per hour, false alerts per hour (no 5-minute danger event within 20 minutes), minutes of warning, share of events caught, with patient-bootstrap confidence intervals.
- **Results, held-out (52 patients, looked at four times, so optimistic):** forecast error 30-55% below no-change; cautious quantiles 9-11% beyond the line; as an alarm it ties Rule 2 at equal alert rates. **Fresh patients (80 patients, 3,931 h, 393 events, partial batch2):** MAE 0.94 / 1.30 / 1.97 / 1.85 / 3.09 (SpO2 low, breathing low and high, HR low and high) against no-change 1.27 / 2.82 / 3.49 / 3.11 / 4.33; beyond-cautious 9.4-11.2%; at the shipped cutoff 0.574 alerts/h, 77.6% false, 25.8 minutes of warning and 0.68 caught (uncapped, generous). **Capped (quote this; alert in the final 20 minutes only; later batch2 download: 203 patients, 10,653 h, 1,295 events):** at the shipped cutoff 4.3 minutes of warning per event [3.7, 4.8], 0.43 of events caught in time, 72.7% false; at cutoff 1.0, 11.2 minutes and 0.95 caught at 2.04 alerts/h, 85.6% false. See decisions.md "T6 capped warning metric".
- **Known limits:** ICU patients sit near the edges, so alert rates overstate a waiting room; strap breathing rate is not MIMIC's impedance respiration; SpO2 is simulated in the demo; HR events are rare (53 events from 17 patients), so the HR forecasts say little about alarms.

### Running it live

`backend/risk_engine/fast_model.py` runs every minute on the rolling one-minute history (`trend.py`), after 15 clean minutes and never while a vital is in danger; about 0.2 ms per prediction after a 0.5 s lazy load (LightGBM needs libomp on Mac, libgomp on Linux; without it the fast model is off and the rest runs). The tier feeds the alert logic in section 5. Retrain when the second batch finishes (decisions.md, "T6 ship").

## 5. Signal quality, breathing rate and alert logic

These are rules and estimators with tuned thresholds. Alert thresholds are tuned by replaying eICU. We do not validate the breathing-rate estimate ourselves; we rely on the published H10 results below.

### Breathing rate from the chest strap

Breathing modulates heart rate: it rises on inhaling and falls on exhaling (respiratory sinus arrhythmia), so breathing rate can be estimated from beat-to-beat intervals ([Charlton 2017 review](https://pmc.ncbi.nlm.nih.gov/articles/PMC7612521/)).

| Method | Evidence on the Polar H10 | Our use |
| --- | --- | --- |
| From beat-to-beat intervals | r = 0.85 against gas-exchange reference, median bias about 1 breath/min, 21 people on an exercise ramp ([Rogers 2022, Sensors](https://pmc.ncbi.nlm.nih.gov/articles/PMC9573071)); 5.5–7.6% error with two algorithms during running ([EPFL](https://infoscience.epfl.ch/signposting/describedby/eefedefe-b1e1-40bf-a51d-246e9b3c4127)) | Primary method; works over the standard heart-rate profile |
| From chest accelerometer | No H10-specific validation found | Not used |

### Signal quality

- **Strap contact:** the standard heart-rate message carries a sensor-contact flag ([Bluetooth Heart Rate Service](https://www.bluetooth.com/specifications/specs/heart-rate-service-1-0/)); minutes without contact are discarded.
- **Beat intervals:** drop intervals outside a physiologic range (30–200 bpm) and sudden jumps relative to neighbouring beats; the jump threshold is tuned on our own recordings.
- Every discarded minute is logged, and its count feeds the dashboard so the nurse knows when a patient's data is thin.

### Alert logic

An alert fires when any of these holds for its persistence window:

1. A vital in the danger tier, or aggregate NEWS2 of 5 or more (the urgent threshold; [NHS Scotland NEWS2 guideline](https://rightdecisions.scot.nhs.uk/media/vhcccgq2/news2-guideline-no-fp.pdf)).
2. A vital in warning for longer than its window.
3. Trend-model score above its cutoff (warning tier) for its window.

**Why persistence windows:** short delays cut nuisance alarms sharply. A 15-second delay plus a lower SpO2 threshold cut alarms by 70% in post-surgical patients, and a 15-second delay alone cut SpO2 alarms by 67% in preterm infants (both summarized in [this ICU alarm review](https://www.ncbi.nlm.nih.gov/pmc/articles/PMC4891882/)).

**Tuning the windows:** replay eICU stays and, for windows from 1 to 15 minutes, count alerts per patient-hour among survivors (nuisance) and how early non-survivors are first flagged. Pick the window where nuisance alerts stop falling quickly but first flags are not yet delayed much.

**Escalate-only:** alerts stay on the dashboard until a nurse acknowledges them; they never clear themselves.

## Limits

The biggest limit is setting: every training dataset is survey or ICU data, and none comes from an ER waiting room. State these in the pitch.

- **Population shift.** NHANES is healthy people at rest; PhysioNet 2019 and eICU are ICU patients. Waiting-room patients sit in between.
- **Coverage of vitals.** Only heart rate and BP have feature-conditioned population data; SpO2, breathing rate and temperature rely on single published studies and NEWS2.
- **SpO2, temperature and triage BP are simulated** in the demo: in live mode SpO2 and temperature are filled in, in a run every vital follows a script, and the six sample patients carry their own triage BP, until real sensors are added.
- **Trend history in demo runs is scripted.** Each run starts the trend models with 120 minutes of starting-value rows (chosen for the sepsis slow model, which is now dropped; the fast model's longest window is 30 minutes), so their first two hours of look-back are invented; the slow model's 3 and 6 hour windows are still only partly filled.
- **Blood pressure is a single triage reading,** so a BP drop during the wait goes unseen.
- **NEWS2 in a waiting room.** It was validated mainly on admitted patients.
- **Small subgroups.** Some drug classes will have too few NHANES users to estimate their own shift; those fall back to guideline rules.
- **Limited outcome types.** The fast model learns short-term vital instability (no dedicated sepsis model); other causes rely on the bands and NEWS2. The fast model's labels come from the same vitals it reads, which is why it must beat simple baselines.
- **Self-written adjuster test set.** It reflects what we thought to test.
- **Research prototype.** A deployed version would be a regulated medical device.

### Not verified, so not relied on

- No numeric heart-rate cutoff was found for diabetic autonomic neuropathy, so there is no diabetes rule beyond what NHANES shows.
- No source was found for anticholinergics raising heart rate, so that rule is excluded.
- Breathing rate from the H10's accelerometer has no published validation, so it is not used.
- That the H10 keeps a second Bluetooth connection alive while streaming accelerometer data: Polar documents two connections, but not this combination.
- LightGBM's `pred_contrib` option was not checked against the docs in this pass.

## Sources

Datasets

- [NHANES 2017 examination files](https://wwwn.cdc.gov/nchs/nhanes/search/datapage.aspx?Component=Examination&CycleBeginYear=2017) · [2021 files](https://wwwn.cdc.gov/nchs/nhanes/search/datapage.aspx?Component=Examination&CycleBeginYear=2021) · [RXQ\_DRUG drug classes](https://wwwn.cdc.gov/Nchs/Data/Nhanes/Public/1988/DataFiles/RXQ_DRUG.htm)
- [PhysioNet/CinC 2019 Sepsis Challenge](https://physionet.org/content/challenge-2019/1.0.0/) · [Reyna 2020](https://pmc.ncbi.nlm.nih.gov/articles/PMC6964870/)
- [eICU-CRD demo](https://physionet.org/content/eicu-crd-demo/2.0.1/) · [MIMIC-IV-ED demo](https://physionet.org/content/mimic-iv-ed-demo/2.2/)

* [MIMIC-III Waveform Database, matched subset](https://physionet.org/content/mimic3wdb-matched/1.0/)

Thresholds and guidelines

- [RCP NEWS2 report](https://www.rcp.ac.uk/media/a4ibkkbf/news2-final-report_0_0.pdf) · [MDCalc NEWS2](https://www.mdcalc.com/calc/10083/national-early-warning-score-news-2) · [NHS Scotland NEWS2 guideline](https://rightdecisions.scot.nhs.uk/media/vhcccgq2/news2-guideline-no-fp.pdf) · [RCN NEWS2 card](https://startingout.rcn.org.uk/Develop/Nursing-Essentials-Crib-Cards/NEWS2)
- [IDSA fever in older adults, High 2009](https://pmc.ncbi.nlm.nih.gov/articles/PMC7166905)

Reference ranges and modifiers

- [Obermeyer 2017, temperature](https://www.bmj.com/content/359/bmj.j5468.long) · [Apple Heart & Movement Study, SpO2](https://pmc.ncbi.nlm.nih.gov/articles/PMC10374661) · [Vold 2015, SpO2](https://bmcpulmmed.biomedcentral.com/articles/10.1186/s12890-015-0003-5) · [Quer 2020, resting HR](https://pmc.ncbi.nlm.nih.gov/articles/PMC7001906)
- [Beta-blockers in sepsis, J Intensive Care 2021](https://doaj.org/article/534b643510c745418abca8a5271d43d8) · [Antidepressants and HR, Licht](https://pmc.ncbi.nlm.nih.gov/articles/PMC3442343) · [Pregnancy vitals, Loerup 2019](https://bmcmedicine.biomedcentral.com/track/pdf/10.1186/s12916-019-1399-1)

Signals, methods and monitoring

- [Charlton 2017, breathing rate from ECG/PPG](https://pmc.ncbi.nlm.nih.gov/articles/PMC7612521/) · [Rogers 2022, H10 breathing rate](https://pmc.ncbi.nlm.nih.gov/articles/PMC9573071) · [EPFL, H10 RR-interval breathing](https://infoscience.epfl.ch/signposting/describedby/eefedefe-b1e1-40bf-a51d-246e9b3c4127)
- [Bluetooth Heart Rate Service](https://www.bluetooth.com/specifications/specs/heart-rate-service-1-0/) · [LightGBM parameters](https://lightgbm.readthedocs.io/en/latest/Parameters.html) · [Murphy, conjugate Gaussian](https://www.cs.ubc.ca/~murphyk/Papers/bayesGauss.pdf)
- [ICU pulse-oximeter alarm review](https://www.ncbi.nlm.nih.gov/pmc/articles/PMC4891882/) · [SNAP40-ED study](https://www.pagepressjournals.org/ecj/article/view/9711) · [veri.studio](https://www.veri.studio/lahacks)

Numbers marked "checked by download" were measured on the files themselves during this research.
