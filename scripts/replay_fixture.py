"""Replay fixtures through the risk engine and print what happens.
Use when checking the engine on eICU stays (intake from the stays file) or the synthetic wearer.
Usage:
  uv run python -m scripts.replay_fixture [stay_id] [--no-intake] [--out path.jsonl]
  uv run python -m scripts.replay_fixture --wearer
  uv run python -m scripts.replay_fixture --i6 fixtures/wearer_drift_i6.jsonl
  uv run python -m scripts.replay_fixture [stay_id | --i6 PATH] --alerts [--ack-after 10]
  uv run python -m scripts.replay_fixture [stay_id] --adjust
--i6 replays any one-patient I6 file and prints each minute's vital levels and trend fields
(the wearer's id gets the fixture intake, anything else runs with no intake).
--alerts also runs alert logic on each I9 and prints the I10 stream (ALERT / RESOLVED lines, with
what each alert supersedes); --ack-after N simulates a dashboard ack N minutes after every alert.
--adjust runs the structured adjuster rules (age, drug classes, pregnant flag; no LLM) on each stay's
intake and passes the I5 to on_intake, then prints the I8 danger edges that moved.
--out writes the I9 rows; it is never written by default, so fixtures/eicu_i9.jsonl (the recorded
stand-in used by alert logic and the Fetch.ai agent) is only replaced when asked for."""
import argparse
from pathlib import Path

from datetime import timedelta

from backend.adjuster.adjuster import adjust_structured
from backend.contracts import Acknowledgment, AlertConfig, PatientContext
from backend.fixtures import DIR, iter_i13, load_context, load_i6, load_stays, stay_rows
from backend.risk_engine.alerts import AlertLogic
from backend.risk_engine.engine import RiskEngine


def _short(alert_id):
    pid, key, ts = alert_id.split("|")
    return f"{key}@{ts[11:16]}"


class AlertPrinter:
    """Runs AlertLogic beside a replay: feed it every I9, it prints the I10 stream and a per-stay count.
    With ack_after set, every new alert is acknowledged that many minutes later (simulated dashboard)."""

    def __init__(self, eng, ack_after):
        self.logic = AlertLogic(eng.config.alerts or AlertConfig(), eng.bed_label)
        self.ack_after, self.pending = ack_after, []
        self.counts = {"alerts": 0, "resolved": 0, "acks": 0}
        self.live = {}  # alert_id -> key, for the one-open-alert-per-key check

    def feed(self, i9):
        due = [a for a in self.pending if a.ts <= i9.ts]
        self.pending = [a for a in self.pending if a.ts > i9.ts]
        for a in sorted(due, key=lambda a: a.ts):
            head = a.alert_id
            while head in self.logic._superseded_by:  # the ack lands on the chain's head
                head = self.logic._superseded_by[head]
            if self.logic.on_ack(a):
                self.counts["acks"] += 1
                ak = head.split("|")[1]
                self.live = {i: k for i, k in self.live.items() if k != ak}  # acked: no longer an open alert
                print(f"  {a.ts:%H:%M} ACK      {_short(head)}")
        for e in self.logic.on_risk(i9):
            key = e.alert_id.split("|")[1]
            if e.resolved:
                self.counts["resolved"] += 1
                print(f"  {e.ts:%H:%M} RESOLVED {_short(e.alert_id)}")
                continue
            self.counts["alerts"] += 1
            for s in e.supersedes:
                self.live.pop(s, None)
            assert key not in self.live.values(), f"two open alerts for {key}"
            self.live[e.alert_id] = key
            sup = f" supersedes={[_short(s) for s in e.supersedes]}" if e.supersedes else ""
            print(f"  {e.ts:%H:%M} ALERT    {e.severity:7s} {e.trigger:17s} {e.message} "
                  f"[{_short(e.alert_id)}]{sup}")
            if self.ack_after is not None:
                self.pending.append(Acknowledgment(alert_id=e.alert_id, ts=e.ts + timedelta(minutes=self.ack_after)))

    def summary(self):
        c = self.counts
        print(f"  alerts {c['alerts']}, resolved updates {c['resolved']}, acks {c['acks']} "
              f"(no key ever had two open alerts)")


def replay_stays(only, intake, out, alerts=False, ack_after=None, adjust=False):
    rows, eng, i9_out = load_i6(), RiskEngine(), []
    for stay in load_stays():
        pid = stay["patient_id"]
        if only and only != pid:
            continue
        if intake:
            ctx = PatientContext(patient_id=pid, age=stay.get("age"), sex=stay.get("sex"))
            res = adjust_structured(ctx) if adjust else None
            eng.on_intake(ctx, res.i5 if res else None)
            if res:
                t = eng.intake_ranges[pid].temp_c
                print(f"{pid} age {ctx.age}: I5 {[(a.rule_id, a.vital, a.bound, a.value) for a in res.i5.adjustments]}; "
                      f"temp danger_high {t.danger_high}, safe_high {t.safe_high}")
        srows = stay_rows(rows, pid)
        by_ts = {r.period_ts: r for r in srows}
        path, levels, first_personal = [], {}, None
        ap = AlertPrinter(eng, ack_after) if alerts else None
        if ap:
            print(f"{pid} {stay['outcome']}")
        for w in iter_i13(srows):  # no sleeping: fast-forwarded
            i14 = eng.on_second(w)
            if w.window_end_ts in by_ts:
                i9 = eng.on_period(by_ts[w.window_end_ts])
                i9_out.append(i9.model_dump_json())
                if ap:
                    ap.feed(i9)
                levels[i9.level] = levels.get(i9.level, 0) + 1
                path.append(i14.news2)
                cur = eng.ranges[pid]
                if first_personal is None and "personal" in (cur.hr.source, cur.resp_rate.source):
                    first_personal = w.window_end_ts
        peak = max((p for p in path if p is not None), default=None)
        print(pid, stay["outcome"], "levels", levels, "peak NEWS2", peak, "first personal band", first_personal)
        if ap:
            ap.summary()
        r = eng.ranges[pid]
        print(f"  HR safe {r.hr.safe_low}-{r.hr.safe_high} ({r.hr.source}), "
              f"breathing safe {r.resp_rate.safe_low}-{r.resp_rate.safe_high} ({r.resp_rate.source})")
    if out:
        Path(out).write_text("".join(l + "\n" for l in i9_out))
        print(f"wrote {len(i9_out)} I9 rows to {out}")


def replay_wearer():
    eng = RiskEngine()
    eng.on_intake(load_context())
    pop = eng.intake_ranges["demo-001"].hr
    print(f"population HR safe {pop.safe_low}-{pop.safe_high}  reasons: {pop.reasons}")
    for i, m in enumerate(load_i6(DIR / "wearer_drift_i6.jsonl")):
        res = eng.on_period(m)
        hr = eng.ranges[m.patient_id].hr
        if i % 5 == 4:
            print(f"min {i + 1:2d} HR {m.hr:5.1f} band {hr.safe_low}-{hr.safe_high} ({hr.source}) -> {res.level}")


def replay_i6(path, alerts=False, ack_after=None):
    eng, rows = RiskEngine(), load_i6(Path(path))
    ctx = load_context()
    if rows and rows[0].patient_id == ctx.patient_id:
        eng.on_intake(ctx)
    ap = AlertPrinter(eng, ack_after) if alerts else None
    for i, m in enumerate(rows):
        r = eng.on_period(m)
        if ap:
            ap.feed(r)
            continue
        lv = " ".join(f"{k}={v}" for k, v in r.vital_levels.model_dump().items() if v)
        print(f"min {i + 1:2d} {r.level:7s} [{lv}] trend prob={r.trend_prob_fast} "
              f"tier={r.trend_tier} reason={r.trend_reason_fast}")
    if ap:
        ap.summary()


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("stay", nargs="?")
    ap.add_argument("--no-intake", action="store_true", help="replay with no intake: plain NEWS2 bands")
    ap.add_argument("--wearer", action="store_true")
    ap.add_argument("--i6", help="replay one patient's I6 file, printing levels and trend fields")
    ap.add_argument("--adjust", action="store_true", help="apply structured adjuster rules (no LLM) at intake")
    ap.add_argument("--out")
    ap.add_argument("--alerts", action="store_true", help="also run alert logic and print the I10 stream")
    ap.add_argument("--ack-after", type=float, help="with --alerts: ack every alert this many minutes later")
    a = ap.parse_args()
    if a.i6:
        replay_i6(a.i6, a.alerts, a.ack_after)
    elif a.wearer:
        replay_wearer()
    else:
        replay_stays(a.stay, not a.no_intake, a.out, a.alerts, a.ack_after, a.adjust)
