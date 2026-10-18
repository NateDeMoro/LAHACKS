"""The limit menu (I7 limit_menu.json): the only numbers a drafted rule can use. The model picks an id;
code turns it into a new safe-band edge for one patient. Values are checked when the menu loads."""
import json
from pathlib import Path

from backend.config import CONFIG
from backend.contracts import LimitMenu, MenuEntry
from backend.risk_engine.ranges import SCORE0

# Narrowest safe band a drafted step may leave, in the vital's units.
MIN_WIDTH = {"hr": 16, "resp_rate": 4, "spo2": 2, "temp_c": 0.6}


def load_menu(path: Path | None = None) -> LimitMenu:
    menu = LimitMenu.model_validate(json.loads((path or CONFIG.conditions.menu_path).read_text()))
    seen: set[str] = set()
    for e in menu.entries or []:
        if e.id in seen:
            raise ValueError(f"duplicate menu id {e.id!r}")
        seen.add(e.id)
        if e.kind == "relative" and not (e.amount and e.amount > 0):
            raise ValueError(f"{e.id}: relative amount must be positive")
        if e.kind == "absolute":
            lo, hi = SCORE0[e.vital]
            if not lo < e.amount < hi:
                raise ValueError(f"{e.id}: absolute value {e.amount} is outside the score-0 range {lo}-{hi}")
    return menu


def allowed(menu: LimitMenu, vitals: tuple[str, ...]) -> list[MenuEntry]:
    return [e for e in menu.entries or [] if e.vital in vitals]


def target_edge(entry: MenuEntry, safe_low: float, safe_high: float) -> float | None:
    """New safe edge for this step, or None when it would not tighten the band or would leave it too narrow."""
    if entry.kind == "relative":
        edge = safe_high - entry.amount if entry.bound == "high" else safe_low + entry.amount
    else:
        edge = entry.amount
    edge = round(edge, 1)
    new_low, new_high = (safe_low, edge) if entry.bound == "high" else (edge, safe_high)
    tightens = edge < safe_high if entry.bound == "high" else edge > safe_low
    if not tightens or new_high - new_low < MIN_WIDTH[entry.vital]:
        return None
    return edge
