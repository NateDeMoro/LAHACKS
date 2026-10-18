# Sentry Findings

What Sentry showed us and what we changed because of it. Fill a row only after the Sentry view has shown the answer; the pitch uses these rows. Plan: [Sentry plan artifact](https://claude.ai/artifact/PFB58PcmjcMZyngAJTBZF6).

## What is instrumented

| Where | What Sentry gets |
| --- | --- |
| `backend/observability.py` | One init for backend and receiver: tracing, logs, profiling, OpenAI integration (prompts off), PII off, `service` tag. No `SENTRY_DSN` keeps it off |
| Receiver (`receiver/`) | A sampled trace per frame (frame processing, then send); logs for strap connect, contact lost and regained, breathing estimate reason changes, slow-socket drops. Trace headers ride in the I1 envelope |
| Ingest (`backend/app.py`, `backend/ingest/service.py`) | `ingest reading` continues the receiver's trace with `strap_to_ingest_s`; `ingest tick` (sampled) with a news2 span; `engine period` (always, profiled); `GET /health` for the uptime check |
| LLM (`backend/llm.py`, `backend/intake/service.py`) | `llm.json_completion` span (retried, tokens) around the OpenAI AI span; `intake adjust` transaction in the intake request's trace with `adjuster.llm_ok`, `cache_hit`, `dropped`; a log when the adjuster falls back to rules only |
| Frontend (`frontend/src/main.tsx`) | Browser tracing and Session Replay (inputs masked) when `VITE_SENTRY_DSN` is set |

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
