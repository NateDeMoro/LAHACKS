# Agentic LLM Plan: Custom Conditions and Fetch.ai Agents

Oct 18, 2026

Plan for growing the context adjuster into a small agentic system. A nurse can type any condition, the system checks it against public vocabularies, and limits change only through cited rules. Contracts are in [component-map.md](component-map.md) (I2, I4, I5, I15 changed; I16 and I17 new). Steps are in [build-order.md](build-order.md) (F1–F3, K1–K5, C5). Nothing here is built yet.

## Goal

A nurse types a condition in ASI:One or on the intake form. The system looks it up in a public vocabulary. If a table rule exists (`models/rules.json`), it applies as today. If the condition is real but has no rule, an evidence agent picks a vital, a bound and a limit from a preset menu and cites its sources; the result applies for that patient only, as a warning, labeled unreviewed. The tool stays advisory: the nurse decides who is seen early, so there is no review queue in the LLM component.

Guarantees, each enforced in code:

| Guarantee | Enforced by | State |
| --- | --- | --- |
| A term outside the public vocabularies never moves a limit (a near-miss spelling of a real name can match; a rare real condition can miss) | Vocabulary lookup | New |
| Every change shows a source that resolves | Citation gates | New |
| Limits only move toward danger sooner | `ranges.apply_i5` clamp | Built |
| The model never writes a number: table values come from `rules.json`, and a drafted rule picks an entry from a limit menu set ahead of time (`models/limit_menu.json`) | Output type has no number field; menu loaded and checked in code | Changed |
| A drafted rule moves the warning edge only, applies to one patient, and never enters the shared table | Engine warning tier, scope in code | New |

Targets, proposed and measured on a test set we build first. Treat them as a smoke test, not a safety proof: with 7 rules and 10 abstention cases the 95% intervals are wide (8 of 10 is about 49% to 94%, 5 of 7 about 36% to 92%; Wilson intervals, our arithmetic).

| Measure | Today | Target |
| --- | --- | --- |
| Invented conditions that change a limit | Impossible (fixed checklist) | 0 of 40, hard gate |
| Invented conditions answered "not found" | n/a | At least 38 of 40 |
| Real conditions resolved to a code (common, rare, lay terms, typos) | 10 of 10 on the checklist | At least 54 of 60 |
| Cited sources that resolve and contain the quoted passage | Not measured | 100%, by script |
| Condition-field injection strings that alter a limit | Not measured | 0 of 20 |
| Model-written numbers that reach the engine | n/a | 0, the output has no number field |
| Drafted rules that reach the danger edge | n/a | 0, hard gate |
| Drafted rules written to `rules.json` by the system | n/a | 0 |
| Adjuster test split, precision / recall | 1.000 / 0.982 | No drop |
| Numbers in a reply missing from the computed table | Not measured | 0 |
| First reply waits on a model call | No | No |

## Settled decisions

- Drafted rules are on from the start. One config flag turns them off if a demo or test shows a problem. No advisory-first phase and no release gate.
- Restrictions on a drafted rule: warning edge only, never danger (same precedent as the fast trend model, which never raises above warning); the value comes from a limit menu set ahead of time, never from the model; a small cap per patient; one patient only; never written to `rules.json`; labeled "unreviewed" on the reply and on the I8 reason line.
- The model never writes a number. The limit menu is a small table in `models/limit_menu.json`, set ahead of time and reviewed by a clinician once (not per patient). For each vital and bound it lists a few warning values, each with an id, a label and a source. The evidence agent returns a vital, a bound and a menu id, or none; code looks up the value. Every menu value is checked against the warning band when the menu loads. The first draft reuses numbers already in `rules.json` (those are danger edges there, so their meaning as warning edges needs a deliberate decision); the team sets the final entries. Each entry's alert load can be measured once by replaying eICU stays with the existing replay tooling.
- Gates replace the human review queue: IDs resolve, titles match, the passage is in the abstract, two distinct sources each name the chosen vital in their passage (a text match, a weak proxy for support), the source is a guideline, review or trial (PubMed publication type, to confirm), and the pick is a real menu id. Two runs of the same model agreeing is not a gate.
- Evidence is saved with each draft (papers, passages, hash) and reused for that condition, so the same condition gives the same limits on any day.
- Promotion to a permanent rule is a normal commit to `rules.json` by a reviewer reading the log. Nate's hand review of the seven current rules is the model for that review.
- No nurse messaging, no acknowledge from chat (I11 stays dashboard only), no recheck ranking. Risk shows as level colors and open alerts.
- Every model call goes through `backend/llm.py` to step-5-preview. Pydantic stays the only JSON layer (no Instructor, no PydanticAI); closed `Literal` sets, `extra="forbid"` and length caps go on every new schema, and the code-side gates above cover what a schema cannot.

## Architecture

Four registered agents, three with a model stage. Only the coordinator talks to ASI:One. The line that matters runs between each model stage and the code stage after it: text from a patient or from PubMed reaches a model that cannot write, and the script that writes sees only validated output (Meta's Agents Rule of Two, [Willison's summary](https://simonw.substack.com/p/new-prompt-injection-papers-agents)).

| Agent | Model stage | Code stage | Model can write |
| --- | --- | --- | --- |
| Coordinator | Turns the nurse's message into a plan (a JSON list of steps naming tools from a fixed set) and fills the intake fields | Validates the plan and the intake fields, runs tools, caps steps and tokens, re-plans twice at most | No |
| Intake | Normalizes typed conditions; reads the chief complaint for facts and quotes (existing adjuster) | Vocabulary lookup, rule match, validator, clamp; writes I5 and I15 | No |
| Evidence | Searches PubMed read-only and picks a vital, a bound and a menu step (or none) from abstracts; sees no patient data | Gates, looks up the menu value, then the clamp for that patient's warning edge | No |
| Monitor | None | Reads a patient's latest I9 level and open I10 alerts, fills reply templates | No model |

Coordinator tools: register patient (wraps `POST /intake` and the poll on `GET /intake/{patient_id}`), risk status, run scenario (`POST /sim/run`). Two permission tiers: reads, and reversible writes. A tool gateway keeps the call log, so the agent does not report on itself. Replies come from templates over typed data; a script checks that every number in the text is in that data. There is no writer model.

Flow for one typed condition:

1. Intake validates I2 in code (custom conditions length-capped, control characters stripped) and returns code-only limits at once.
2. Normalize (one model call, sees only the typed strings): canonical term, synonyms, search terms.
3. Look up in NLM Clinical Tables (conditions, ICD-10-CM), fuzzy-match in code: found with a code, not found, or several matches. Several matches: the coordinator asks the nurse which was meant (a question, no write) and the step runs again. Not found: nothing changes, the reply says so, the attempt is logged.
4. Rule match: vocabulary code to a `rules.json` entry. Found: the existing adjuster path runs unchanged.
5. No rule: the evidence agent picks from the limit menu (or none) and gates run. All pass: I17 is emitted with the menu id, code looks up the value, and it is applied as a warning for that patient. Any fail: nothing moves, the nurse sees the suggestion marked not applied, and the failed gates are logged.
6. Reply: templated, showing the code, quote, source, value and evidence label, with "unreviewed" on drafts.

The first reply never waits on a model call (the existing two-step I5). The normalize call, the adjuster call and the evidence pass are 25–45 s each (`backend/llm.py`) and the lowest StepFun tier allows 5 concurrent calls, so a drafted rule lands minutes after intake. A repeat condition is served from the evidence cache.

## Stack

| Piece | Choice | Why |
| --- | --- | --- |
| Model | step-5-preview through `backend/llm.py` | Already the adjuster's model; satisfies the StepFun challenge; one provider |
| JSON | Pydantic plus the existing one-retry helper | Already generates the schema sent to StepFun and validates the reply |
| Condition vocabulary | NLM Clinical Tables, [conditions](https://clinicaltables.nlm.nih.gov/apidoc/conditions/v3/doc.html) and [ICD-10-CM](https://clinicaltables.nlm.nih.gov/apidoc/icd10cm/v3/doc.html) | Free; conditions list is about 2,400 entries. MONDO, Orphanet or UMLS could widen it (licences not checked) |
| Citation checks | [NCBI E-utilities](https://dataguide.nlm.nih.gov/eutilities/how_eutilities_works.html) for PMIDs, [Crossref](https://crossref.org/documentation/retrieve-metadata/rest-api) for DOIs | An ID that resolves is necessary, not sufficient, so title, year and passage are checked too. In a 2023 study, 55% of GPT-3.5 and 18% of GPT-4 citations were fabricated ([Walters and Wilder](https://www.ncbi.nlm.nih.gov/pmc/articles/PMC10484980/)) |
| Fetch.ai | uAgents with the Chat Protocol and Agentverse mailbox (details unverified: the docs did not load from the build sandbox, see [chat protocol guide](https://uagents.fetch.ai/docs/guides/chat_protocol)) | Mandatory for the track; own folder and dependency group, run as a separate process that calls the backend over HTTP |

Three of the seven current rules (chemo_fever, opioid, beta_blocker) cite only guideline PDFs, a hospital web page or a DOAJ listing, which a PubMed check cannot verify. The checker needs a second path for guideline documents (fetch the document, find the passage), or those rules stay as hand-verified table rules.

## Planned layout (not created yet)

| Path | Holds |
| --- | --- |
| `agents/` | The four uAgents, the tool gateway, a README for the track submission |
| `backend/conditions/` | Normalizer, vocabulary lookup, rule matcher, evidence agent, gates, evidence store |
| `backend/risk_engine/ranges.py` | A warning-tier path beside `apply_i5` (narrows the safe edge, leaves danger alone) |
| `models/limit_menu.json` | The limit menu (an I7 file): per vital and bound, a few warning values with an id, a label and a source each |
| `backend/config.py` | A conditions section: kill switch, per-patient cap, match threshold |
| `fixtures/conditions/` | Test sets and the rule-match labels |
| `scripts/score_conditions.py` | Scores each layer, same shape as `score_adjuster.py` |

## Test plan

Each layer gets a labeled file and a scoring script: build on dev, score test once, cache off, repeat runs.

| Layer | Data | Passes when |
| --- | --- | --- |
| Lookup | Lay terms and typos; a rare-disease list; clinician-written diagnosis strings if the eICU or MIMIC tables are on hand (not checked, `/data` is gitignored); invented names generated then dropped if they match NLM or an exact PubMed phrase; real names with a word swapped; terms that match several entries; 20 injection strings | Targets 1–3 and 5 |
| Rule match | About 25 conditions hand-labeled with the expected rule or none | Every label, no model in the loop |
| Citation gates | The sources in `rules.json` as known-good; known-bad made by changing a PMID digit, pairing a real PMID with another title, rewording the quote | Accepts every good, rejects every bad |
| No-rule path | The seven rules as an answer key (below) plus 10 conditions with no known effect on vital signs | Hit rates below |
| Agents end to end | About 30 phrasings against a stub backend; failure drills (backend down, step-5-preview timeout, NLM down) | Every plan valid and within caps, no call outside the tools, no write to `rules.json`, a failed lookup falls back to code-only limits |
| Regression | The 30 dev and 70 test adjuster cases | Precision 1.000, recall at least 0.982 |

Leave-one-rule-out comparison: hide one of the seven rules, send its trigger (the condition, or the drug for the three drug rules) through the no-rule path, and compare the draft with the hidden rule.

| Compared | Scored as | Target |
| --- | --- | --- |
| Vital and direction | Same vital and bound | At least 5 of 7 |
| Menu pick | The picked menu entry is the one nearest the hidden value, or one step away | At least half of the matches |
| Wrong-way proposals | Loosens a limit, reaches the danger edge or sits outside the window | 0, hard gate |
| Abstention | 10 conditions with no known effect on vitals; the agent drafts nothing | At least 8 of 10 |
| Citations | ID, title and passage on every draft | 100% |
| Stability | Same vital and direction over 3 repeat runs | 3 of 3 |
| Source authority | Finds a guideline, review or trial, judged by hand | Judged by hand |

Limits: seven is a smoke test, and because the menu holds the hidden rules' own numbers it measures picking the right vital and step, not recalling a number. Four of the seven are not conditions (three drugs and an age band), so they exercise the evidence agent but not the lookup. The rules were written from literature the model may also know, so recovering them shows it finds the mainstream answer, not that it copes with a rare condition. Beta blocker at 110 bpm and age 65 at 37.8 °C are flagged in `rules.json` as unconfirmed, so a disagreement there is a finding. Add answer keys we did not write (for example NEWS2's own SpO2 Scale 2 for hypercapnic respiratory failure, from memory, confirm in the Royal College of Physicians document).

## Risks and open items

- Vocabulary coverage: rare real conditions may return "not found". Fuzzy matching can map an invented near-miss to a real entry; the word-swapped test names measure it.
- Latency and the 5-concurrent cap (see Architecture). Whether ASI:One accepts a second message after the first reply, and its timeout, are unconfirmed.
- Unverified: uAgents Python and pydantic pins against this project's Python 3.12 and pydantic 2 (hence the separate dependency group); whether PubMed records expose the publication-type field as assumed; whether step-5-preview supports tool calling (the plan-as-JSON coordinator does not need it).
- The seven rules all read "proposed" in `rules.json`. Define what moves a rule to reviewed, and who commits a draft from the log.
- Settings still to choose: the menu entries (with a source each), the cap per patient, the fuzzy-match threshold. A coarse menu can be too aggressive or too lax for a given condition; the replay of each entry measures its alert load once. Because the menu is small, a hand-written ICD-chapter table could cover many conditions without a model, so the evidence agent's value is coverage of conditions that table lacks.
- Chat intake needs a default wearable (`POST /intake` returns 422 without one) and null triage values unless the nurse states them.
- "Advisory" is not a regulatory shield (our understanding, not verified: software that analyzes a signal acquisition system's output sits outside the FDA non-device CDS carve-out). Irrelevant for synthetic patients, relevant to any deployment claim.
- Drafted rules shift the warning edge, which has a 10-minute persistence window against 2 minutes for danger (`models/config.json`). The benefit of a correct draft is an earlier heads-up, not an earlier urgent alert.
