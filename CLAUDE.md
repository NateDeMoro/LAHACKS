# LA Hacks — Hackathon Prototype

## Context
24-hour hackathon build. The goal is a working prototype, not production code.
Speed and working functionality beat scalability, test coverage, and technical polish.

## Overrides to global CLAUDE.md
This file takes precedence over `~/.claude/CLAUDE.md` where they conflict.

| Global rule | Override for this project |
|---|---|
| Test each step before moving on | Verify by running the app and exercising the feature. No unit tests unless explicitly asked. |
| TDD / no-mistakes / PR pipeline | Not used. Commit directly to main after each working slice. |
| Background long checks (lint, typecheck, test suites) | Skip lint and test suites. Only run the build or typecheck when something is broken or before a commit. |
| Update CLAUDE.md after every code change | Update only when a new top-level file or directory is added. Keep the index table current; nothing else. |
| Doc comments with "use when..." triggers | Not required. Comment only non-obvious logic. |
| Don't refactor adjacent code | Still applies. |

## Still applies from global
- Don't edit code until given an imperative. Questions get answers.
- Ask when a request is ambiguous or has multiple reasonable approaches.
- Responses short, plain English first, no time estimates.
- Never commit secrets or `.env` files. Warn if about to.
- Confirm before destructive actions.

## Planning
When asked to plan, produce a thorough code-only plan of what was described. No demo, pitch, or presentation content.
- Stack and key libraries/services, with one-line rationale
- Architecture: components and how they talk
- Data model and API contracts, defined up front so parallel work doesn't collide
- File/directory layout
- Build order in small slices, each leaving the app runnable; riskiest integrations first
- Known risks or unknowns to spike
If code already exists, skim the layout and fit the plan to it; no deep grounding pass. Describe changes in prose, no code snippets.

## Build priorities
- Prefer simple, direct code: hardcoding, mocks, and stubbed data are fine to keep moving.
- Prefer managed services and libraries over hand-rolled infrastructure.
- Never leave the app in a broken state at the end of a change.
- Handle errors only where a failure would crash the app or block the main flow.

## Parallel sessions
- Each person or feature works in its own git worktree on its own branch
  (`git worktree add ../LAHACKS-<name> -b <name>`). Never share one checkout.
- Overrides "commit directly to main": commit on your branch, then rebase on
  main and merge after each working slice. Keep branches short-lived.
- Before starting, run `git worktree list` and `git status` to see what's in flight.
- Don't touch files outside your feature without telling the other person.

## Parallel build rules
- Build each component to its contracts in `notes/component-map.md`; consume neighbours only through those interfaces (I1–I15).
- Test against the listed stand-in, not the real neighbour, until the checkpoint in `notes/build-order.md` says to plug in.
- Changing a contract: update `notes/component-map.md` first, and say which components it affects.

## File index
| Path | Description | Open when |
|---|---|---|
| notes/component-map.md | Components, owners, interface contracts I1–I15, stand-ins | Before building or changing any component, or any data passed between them |
| notes/build-order.md | Parallel lanes, step dependencies, checkpoints C1–C4 | Picking the next piece to build or checking what it depends on |
| notes/stack-reference.md | Tech stack per component, design rules, LLM and agent layer | Choosing a library or tool, or setting up a new component |
| notes/project-overview.md | What we're building, demo plan, hardware, inputs, plain-English risk engine, company challenges, open decisions | Starting work, or needing the why behind a decision |
| notes/risk-model-training-plan.md | Datasets, methods, and evaluation for the risk layer | Building or evaluating the risk scoring, trend models, or alert logic |
| backend/contracts.py | Pydantic models for I1–I15, WebSocket envelope | Passing or validating any interface data |
| backend/risk_engine/ | NEWS2 (news2.py), population ranges (ranges.py), personal baseline (baseline.py), engine (engine.py) | Building or wiring the risk engine, alerts, or dashboard stand-in |
| backend/fixtures.py, backend/timeutil.py | Fixture loaders, I13 expansion; LA time helpers | Needing stand-in I1/I2/I4/I6/I13 data or timestamps |
| fixtures/ | Hand-written I1/I2/I4, eICU I6 rows, stays, recorded I9 | Testing against stand-ins |
| schemas/ | JSON Schema per interface (generated) | B1 output schema or TypeScript type generation |
| models/ | I7 files: config.json (baseline settings), ranges.json (fitted bands) | Changing n₀, windows, cutoffs |
| scripts/ | export_schemas, build_eicu_fixtures, build_wearer_fixture, replay_fixture | Regenerating schemas or fixtures, replaying a stay |
| pyproject.toml, .env.example | uv project (Python 3.12), env key names | Setting up the environment |
| backend/config.py | Central config, one section per component (receiver, breathing) | Changing a setting, threshold or timeout |
| receiver/ | Strap receiver: breathing, frames, strap link, sender, main | Building or changing S1 |
| scripts/hardware/ | Six guided strap checks (scan, connect, rhythm, contact, paced breathing, dropout) | Testing the strap, Bluetooth or breathing on real hardware |
| tests/ | pytest suites, one folder per component (tests/receiver, tests/risk_engine) | Running or adding tests |
| training/ | Offline fits run with uv: fit_ranges.py (NHANES quantile fit to models/ranges.json) | Refitting the population bands |
| notes/decisions.md | Log of every modelling choice, options, evidence | Making or defending a modelling choice |
