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

## File index
| Path | Description | Open when |
|---|---|---|
| notes/architecture-and-build-order.md | System components, data formats, build steps, company challenges | Planning the build order or wiring components together |
| notes/stack-reference.md | Tech stack per component, design rules, LLM and agent layer | Choosing a library or tool, or setting up a new component |
| notes/risk-model-training-plan.md | Datasets, methods, and evaluation for the risk layer | Building or evaluating the risk scoring, trend models, or alert logic |
