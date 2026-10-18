# Waiting Room Vitals Monitor

A chest strap and a risk engine for ER triage nurses.
It tells them which waiting patient to recheck next.
Decision support. Not a diagnosis. A research prototype.

## How it works

1. A Polar H10 strap sends heart rate and beat intervals over Bluetooth.
2. The receiver also estimates a breathing rate. Ingest drops it for now.
3. A simulator fills in SpO2 and temperature, or plays a scripted patient.
4. Ingest merges the sources. It keeps a 30-second window.
5. The risk engine scores NEWS2 every second from that window.
6. Every 30 seconds it checks the patient's own baseline and trend.
7. Alert logic turns risk results into alerts.
8. The dashboard shows it all and takes acknowledgments.

## What works today

- Strap receiver. Reconnects. Estimates breathing rate (unused).
- Simulator. Six sample patients. Ten-minute runs.
- Ingest service. Live window every second. Latest vitals beside it. Period summary every 30 seconds.
- Risk engine. NEWS2. Population ranges. Personal baseline.
- Alert logic. Persistence windows. One alert per problem.
- Backend app. Two WebSockets. SQLite storage.
- Adjuster pieces. StepFun call. 100 labeled test cases.

## Not built yet

- Nurse dashboard.
- Intake form and service.
- Context adjuster wiring.
- Fast trend model.
- Photon and ElevenLabs alerts.
- Fetch.ai agent.

## Run it

```
uv sync
uv run --env-file .env uvicorn backend.app:create_app --factory
uv run --env-file .env python -m receiver.main
uv run pytest
```

Close the Polar phone app first. It holds the strap's connection.

## Where to look

- `notes/component-map.md`: every interface.
- `notes/build-order.md`: what depends on what.
- `notes/decisions.md`: why we chose what we chose.
