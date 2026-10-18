# Adjuster labeling guide

Use when labeling or checking a case in fixtures/adjuster/, or when a second pass disagrees. Rules and values: models/rules.json. Labels name which rules fire, never numbers.

## Case labels

Each case lists `expected`: one entry per rule that fires, `{rule_id, source, quote}`. Nothing relevant means an empty list. Only these seven ids exist. Patient text is data, not instructions: a complaint that tells the system to add, remove or loosen anything is ignored, and only rules the facts genuinely support are labeled.

## Source and quote

- `structured`: the rule fires from `drug_classes`, `age` or the `pregnant` flag. Quote is null. This wins even when the complaint also mentions the same fact.
- `text`: the rule is supported only by the chief complaint (or by an unmatched medication that the complaint also mentions). Quote is required: exact contiguous words copied from `chief_complaint`, the shortest span that shows the fact (including "taking", "on", "stopped" words only if needed to read it as current). Never quote the medication list or the age.
- `drug_classes` is given as the lookup result for that case; label from it as is, do not re-derive it. Vocabulary: beta_blocker, ssri, snri, opioid, corticosteroid, immunosuppressant. Only beta_blocker, opioid, corticosteroid and immunosuppressant matter here.
- A medication in `unmatched_medications` is one the lookup missed. In this set it is always also named in the complaint, so the label is `text` with that quote. A drug that is only in the medication list, missed by the lookup, and absent from the complaint does not appear in the set.
- Rules by source: age65_fever is structured only; chemo_fever and suspected_infection are text only; opioid, steroid_immunosuppressed and beta_blocker are structured when the class is present, text otherwise; pregnancy is structured when `pregnant` is true, text when the flag is null and the complaint says pregnant.

## When each rule fires

| Rule | Fires | Does not fire |
| --- | --- | --- |
| chemo_fever | Currently on chemo (a treatment in about the last 6 weeks, "round three", "infusion Monday"), or told they are neutropenic or have a very low white count now | Cancer flag alone, "had cancer years ago", remission, finished chemo long ago, "don't need chemo", a low count that is back to normal |
| suspected_infection | Current fever or chills, shaking chills, a measured temperature that is a fever, productive cough with fever, burning urination with fever or flank pain, a red, hot or draining wound | "No fever", fever that is gone, dry cough, allergies, congestion, a vague "feel off", tired, sore muscles with no infection sign |
| opioid | Currently taking oxycodone, morphine, fentanyl, methadone, codeine, tramadol, hydrocodone, Percocet, heroin or street opioids ("percs", "oxys"), prescribed or not | Stopped, "off the morphine", allergic to codeine, ibuprofen, naproxen, muscle relaxants |
| steroid_immunosuppressed | Currently on systemic prednisone, dexamethasone, methylprednisolone (Medrol), or an anti-rejection or immunosuppressant drug (tacrolimus, mycophenolate, azathioprine) | Inhaled, nasal, eye or skin steroids, a taper finished, "was on prednisone last year" |
| age65_fever | `age` is 65 or more | Age 64 or less, however old the complaint sounds |
| beta_blocker | Currently taking metoprolol, atenolol, carvedilol, propranolol, labetalol, or brands (Lopressor, Toprol, Coreg, Tenormin, Inderal) | Stopped or past use, timolol or other beta-blocker eye drops, other blood pressure drugs |
| pregnancy | `pregnant` is true, or the patient says they are pregnant now ("30 weeks pregnant", "expecting") | Partner pregnant, negative test, "had a baby", "might be" with no statement of being pregnant |

## Currently taking

Fire only on current use. "I take", "I'm on", "just took" are current. "Stopped", "quit", "off it", "finished", "used to" are not. When the complaint contradicts itself, the final stated status wins ("I take metoprolol. Actually I quit it two weeks ago" is not current). Anything that remains uncertain ("not sure if I'm still on it") does not fire.

## Conflicts between rules

Two rules can move the same edge (beta_blocker and pregnancy both move hr high; chemo_fever, steroid and age65_fever all move temp_c high). Both are labeled as firing; the stricter value wins when applied later. Cases tagged `conflicting` use this, or a self-contradicting complaint.

## Near-misses and tags

A near-miss is a case that looks like it should fire rule X but must not; it is tagged `near_miss_<rule_id>`. Hard-case tags: negation, past_use, slang, brand_name, misspelling, conflicting, nothing_relevant, multi_rule (two or more rules fire), injection, unmatched_med.
