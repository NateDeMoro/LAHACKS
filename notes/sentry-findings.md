# Sentry Findings

What Sentry showed us and what we changed because of it. Fill a row only after the Sentry view has shown the answer; the pitch uses these rows. Plan: [Sentry plan artifact](https://claude.ai/artifact/PFB58PcmjcMZyngAJTBZF6).

## What is instrumented

| Where | What Sentry gets |
| --- | --- |
| `backend/observability.py` | One init for backend and receiver: tracing, logs, profiling, OpenAI integration (prompts off), PII off, `service` tag. No `SENTRY_DSN` keeps it off |
| Receiver (`receiver/`) | A sampled trace per frame (frame processing, then send); logs for strap connect, contact lost and regained, breathing estimate reason changes, slow-socket drops. Trace headers ride in the I1 envelope |
| Ingest (`backend/app.py`, `backend/ingest/service.py`) | `ingest reading` continues the receiver's trace with `strap_to_ingest_s`; `ingest tick` (sampled) with a news2 span; `engine period` (always, profiled); `GET /health` for the uptime check |
| Scoring (`scripts/score_adjuster.py`) | One `eval adjust` transaction per scored case; run with `SENTRY_ENVIRONMENT=eval` to get latency and token numbers apart from demo traffic |
| LLM (`backend/llm.py`, `backend/intake/service.py`) | `llm.json_completion` span named by its `purpose` (retried, tokens) around the OpenAI AI span; `intake adjust` transaction in the intake request's trace with `adjuster.llm_ok`, `cache_hit`, `dropped`; a log when the adjuster falls back to rules only |
| Frontend (`frontend/src/main.tsx`) | Browser tracing and Session Replay (inputs masked) when `VITE_SENTRY_DSN` is set |

## Adding a new LLM feature

1. Call `json_completion(..., purpose="<feature>")`. The OpenAI span, tokens and latency appear on their own; the purpose lets Sentry group by feature.
2. Put cache and store hits on the enclosing span as attributes (`cache_hit`), so a fast call is not mistaken for a fast model.
3. Log fallbacks and failures with ids and counts, never the text.
4. If the work runs in a background task, capture `sentry_sdk.get_traceparent()` and `get_baggage()` before spawning it and continue the trace inside (see `IntakeService._finish`). Do this in a helper once a second feature needs it.
5. Anything that fires every second goes in `READING_OPS` in `backend/observability.py`, or it is traced at 100%.
6. Never put typed or model text in an event. `tests/observability/test_llm_spans.py` fails if a prompt, a reply or a local variable leaks.
7. Add a row to the table above.

## Findings

| Question | What Sentry showed | What we changed | Result |
| --- | --- | --- | --- |
| Spike notes say 25–45 s per LLM call. Is it reasoning tokens or the network? | | | |
| Do breathing rates glitch around dropouts? | | | |
| Which hop owns the time on a reading? | | | |
| Does the per-period engine slow the one-second path? | | | |

## Smoke test, local, fake Sentry and fake LLM (not findings)

- Receiver and ingest spans share one trace id; `strap_to_ingest_s` was about 5 ms on loopback.
- The OpenAI span, the `llm.json_completion` span and the `intake adjust` transaction all land in the intake request's trace.
- Sentry caught the fast trend model failing to load on a machine without `libomp` (`brew install libomp` fixes it).
