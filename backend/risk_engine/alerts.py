"""Alert logic (T4): turns I9 risk results into I10 alerts. Use when wiring the dashboard feed or
replaying recorded I9 rows; feed every I9 to on_risk and every dashboard click (I11) to on_ack.

Keys: one per (patient, vital), one NEWS2 key and one trend key per patient. Each key runs a small
state machine (idle / open / acknowledged; "resolved" is a flag on an open alert). State is in memory.
Persistence is measured from I9 timestamps, not row counts, so 5-minute eICU rows and live 1-minute
rows behave alike."""
import logging
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Callable

from backend.contracts import Acknowledgment, Alert, AlertConfig, RiskResult

log = logging.getLogger(__name__)

VITALS = ("hr", "resp_rate", "spo2", "temp_c")
_RANK = {"warning": 0, "urgent": 1, "high": 2}
_LABEL = {"hr": "heart rate", "resp_rate": "breathing", "spo2": "SpO2", "temp_c": "temperature"}
_UNIT = {"hr": "/min", "resp_rate": "/min", "spo2": "%", "temp_c": "C"}
_DRIVER = {"resp_rate": "breathing", "spo2": "SpO2", "on_oxygen": "oxygen", "sbp": "blood pressure",
           "hr": "heart rate", "alertness": "alertness", "temp_c": "temperature"}
NEWS2_URGENT, NEWS2_HIGH = 5, 7


@dataclass
class _Tier:
    severity: str
    trigger: str
    window: timedelta


@dataclass
class _Key:
    patient_id: str
    kind: str  # a vital name, "news2" or "trend"
    tiers: list[_Tier]  # ascending severity; tier 0's condition is the key's "problem holds"
    state: str = "idle"  # idle | open | acknowledged
    head: Alert | None = None  # the current (latest) alert of this key
    sev: str | None = None
    resolved: bool = False
    runs: list[datetime | None] = field(default_factory=list)  # when each tier's condition started holding
    last_obs: datetime | None = None
    clear_start: datetime | None = None
    ack_ts: datetime | None = None
    acked_sev: str | None = None
    fire_now: bool = False  # news2 folding just ended: fire at once if still holding

    def __post_init__(self):
        self.runs = [None] * len(self.tiers)


class AlertLogic:
    def __init__(self, config: AlertConfig | None = None,
                 bed_label: Callable[[str], str] | None = None):
        self.cfg = config or AlertConfig()
        self.bed_label = bed_label
        self._keys: dict[str, dict[str, _Key]] = {}
        self._folded: dict[str, bool] = {}
        self._key_of: dict[str, _Key] = {}  # alert_id -> the key that raised it
        self._superseded_by: dict[str, str] = {}
        self._last_ts: datetime | None = None

    # ---- keys -------------------------------------------------------------------------------
    def _mins(self, x: float) -> timedelta:
        return timedelta(minutes=x)

    def _make_key(self, pid: str, kind: str) -> _Key:
        c = self.cfg
        if kind == "news2":
            w = self._mins(c.news2_total_minutes)
            tiers = [_Tier("urgent", "news2_total", w), _Tier("high", "news2_total", w)]
        elif kind == "trend":
            tiers = [_Tier("warning", "trend", self._mins(c.trend_minutes))]
        else:
            tiers = [_Tier("warning", "warning_persisted", self._mins(c.warning_persisted_minutes)),
                     _Tier("urgent", "vital_danger", self._mins(c.vital_danger_minutes))]
        return _Key(pid, kind, tiers)

    def _key(self, pid: str, kind: str) -> _Key:
        keys = self._keys.setdefault(pid, {})
        if kind not in keys:
            keys[kind] = self._make_key(pid, kind)
        return keys[kind]

    @staticmethod
    def _hits(kind: str, r: RiskResult) -> list[bool] | None:
        """Which tiers' conditions hold at this I9; None when the observation is missing."""
        if kind == "news2":
            n = r.news2
            return None if n is None else [n >= NEWS2_URGENT, n >= NEWS2_HIGH]
        if kind == "trend":
            return [r.trend_tier == "warning"]
        lvl = getattr(r.vital_levels, kind, None) if r.vital_levels else None
        return None if lvl is None else [lvl in ("warning", "danger"), lvl == "danger"]

    # ---- messages ---------------------------------------------------------------------------
    def _bed(self, pid: str) -> str:
        try:
            return (self.bed_label(pid) if self.bed_label else None) or pid
        except Exception:
            log.exception("bed label lookup failed for %s", pid)
            return pid

    def _message(self, kind: str, r: RiskResult) -> str:
        bed = self._bed(r.patient_id)
        pts = r.news2_points
        if kind == "news2":
            drivers = []
            if pts:
                scored = sorted(((v, k) for k, v in pts.model_dump().items() if v), reverse=True)
                big = [k for v, k in scored if v >= 2] or [k for _, k in scored]
                drivers = [_DRIVER[k] for k in big]
            tail = f" ({', '.join(drivers)})" if drivers else ""
            return f"{bed}: NEWS2 {r.news2}{tail}"
        if kind == "trend":
            why = f" ({r.trend_reason_fast})" if r.trend_reason_fast else ""
            return f"{bed}: may reach danger soon{why}"
        v = getattr(r.vital_values, kind, None) if r.vital_values else None
        text = f"{bed}: {_LABEL[kind]}" + ("" if v is None else f" {v:g}{_UNIT[kind]}")
        p = getattr(pts, kind, None) if pts else None  # null points (stale NEWS2) are left out
        if p is not None:
            text += f", {p} point{'' if p == 1 else 's'}"
        return text

    # ---- events -----------------------------------------------------------------------------
    def _fire(self, ks: _Key, r: RiskResult, tier: int, out: list[Alert]):
        ts, t = r.ts, ks.tiers[tier]
        sup = [ks.head.alert_id] if ks.state != "idle" and ks.head else []
        if ks.kind == "news2":  # one NEWS2 alert replaces the patient's open vital alerts
            for k in self._keys[ks.patient_id].values():
                if k.kind in VITALS and k.state != "idle":
                    if k.state == "open":
                        sup.append(k.head.alert_id)
                    k.state, k.resolved = "idle", False
        alert = Alert(
            alert_id=f"{ks.patient_id}|{ks.kind}|{ts.isoformat()}", patient_id=ks.patient_id, ts=ts,
            severity=t.severity, trigger=t.trigger, vital=ks.kind if ks.kind in VITALS else None,
            supersedes=sup, resolved=False, message=self._message(ks.kind, r))
        self._key_of[alert.alert_id] = ks
        for s in sup:
            self._superseded_by[s] = alert.alert_id
        ks.head, ks.state, ks.sev, ks.resolved = alert, "open", t.severity, False
        ks.ack_ts = ks.acked_sev = None
        out.append(alert)

    def _step(self, ks: _Key, r: RiskResult, hits: list[bool], folded: bool, out: list[Alert]):
        ts = r.ts
        if ks.last_obs and ts - ks.last_obs > self._mins(self.cfg.max_gap_minutes):
            ks.runs, ks.clear_start = [None] * len(ks.tiers), None  # too long without data
        ks.last_obs = ts
        for i, h in enumerate(hits):
            ks.runs[i] = (ks.runs[i] or ts) if h else None
        ks.clear_start = None if hits[0] else (ks.clear_start or ts)
        want = max((i for i, t in enumerate(ks.tiers)
                    if ks.runs[i] is not None and ts - ks.runs[i] >= t.window), default=None)
        holding = max((i for i, h in enumerate(hits) if h), default=None)
        cleared = ks.clear_start is not None and ts - ks.clear_start >= self._mins(self.cfg.clear_minutes)
        if folded:
            return  # tracking only; the NEWS2 alert speaks for this vital
        fire_now, ks.fire_now = ks.fire_now and holding is not None, False
        sev = lambda i: _RANK[ks.tiers[i].severity]
        if ks.state == "idle":
            if want is not None:
                self._fire(ks, r, want, out)
            elif fire_now:
                self._fire(ks, r, holding, out)
        elif ks.state == "open":
            if want is not None and (ks.resolved or sev(want) > _RANK[ks.sev]):
                self._fire(ks, r, want, out)
            elif cleared and not ks.resolved:
                ks.resolved = True
                ks.head = ks.head.model_copy(update={"ts": ts, "resolved": True})
                self._key_of[ks.head.alert_id] = ks
                out.append(ks.head)
        else:  # acknowledged
            if want is not None and sev(want) > _RANK[ks.acked_sev]:
                self._fire(ks, r, want, out)
            elif holding is not None and ts - ks.ack_ts >= self._mins(self.cfg.ack_cooldown_minutes):
                self._fire(ks, r, holding, out)  # still holding when the cooldown ends: no new window
            elif cleared:
                ks.state = "idle"

    def on_risk(self, r: RiskResult) -> list[Alert]:
        """Feed one I9. Returns the I10 events it causes: new alerts and resolved updates."""
        if not r.patient_id or r.ts is None:
            return []
        self._last_ts = r.ts
        out: list[Alert] = []
        pid = r.patient_id
        n2 = self._key(pid, "news2")
        hits = self._hits("news2", r)
        if hits is not None:
            self._step(n2, r, hits, False, out)
        # vital alerts stay folded while the NEWS2 alert is live (open and unresolved, or acknowledged)
        folded = n2.state == "acknowledged" or (n2.state == "open" and not n2.resolved)
        if self._folded.get(pid) and not folded:
            for v in VITALS:
                self._key(pid, v).fire_now = True
        self._folded[pid] = folded
        for kind in (*VITALS, "trend"):
            ks = self._key(pid, kind)
            hits = self._hits(kind, r)
            if hits is not None:
                self._step(ks, r, hits, folded and kind in VITALS, out)
        return out

    def on_ack(self, ack: Acknowledgment) -> bool:
        """Feed one I11. An ack of any alert in a supersede chain acks the chain's current head.
        Returns True when it changed anything; unknown or stale acks are logged and ignored."""
        head = ack.alert_id
        while head in self._superseded_by:
            head = self._superseded_by[head]
        ks = self._key_of.get(head)
        if ks is None:
            log.warning("ack for unknown alert %s ignored", ack.alert_id)
            return False
        if ks.head.alert_id != head or ks.state != "open":
            log.info("ack for %s ignored (already acknowledged or no longer live)", ack.alert_id)
            return False
        ks.state, ks.acked_sev = "acknowledged", ks.sev
        ks.ack_ts = ack.ts or self._last_ts
        return True
