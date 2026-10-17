"""Write one JSON Schema per interface to schemas/. Use when contracts.py changes."""
import json
from pathlib import Path

from backend.contracts import INTERFACES, WsMessage

out = Path(__file__).resolve().parent.parent / "schemas"
out.mkdir(exist_ok=True)
for iid, model in INTERFACES.items():
    (out / f"{iid}.json").write_text(json.dumps(model.model_json_schema(), indent=2) + "\n")
(out / "envelope.json").write_text(json.dumps(WsMessage.model_json_schema(), indent=2) + "\n")
print(f"wrote {len(INTERFACES) + 1} schemas")
