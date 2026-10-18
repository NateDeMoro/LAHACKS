import asyncio
import sqlite3
from datetime import datetime

from backend.contracts import MinuteSummary, VitalsReading
from backend.ingest.store import Store
from backend.timeutil import LA

T0 = datetime(2026, 10, 18, 9, 0, tzinfo=LA)


def minute(pid, hr, ts=T0):
    return MinuteSummary(patient_id=pid, minute_ts=ts, hr=hr)


async def until(cond, timeout=2.0):
    async with asyncio.timeout(timeout):
        while not cond():
            await asyncio.sleep(0.01)


async def test_rows_written_while_running_are_fetched_in_order_and_filtered(tmp_path):
    store = Store(tmp_path / "db" / "ingest.sqlite")
    task = asyncio.create_task(store.run())
    store.write("I6", minute("a", 70), patient_id="a")
    store.write("I6", minute("b", 80), patient_id="b")
    store.write("I6", minute("a", 71), patient_id="a")
    await until(lambda: len(store.fetch("I6")) == 3)
    assert [r["hr"] for r in store.fetch("I6")] == [70, 80, 71]
    assert [r["hr"] for r in store.fetch("I6", patient_id="a")] == [70, 71]
    assert store.fetch("I9") == []
    task.cancel()
    await asyncio.gather(task, return_exceptions=True)


async def test_cancel_flushes_what_is_queued(tmp_path):
    store = Store(tmp_path / "ingest.sqlite")
    task = asyncio.create_task(store.run())
    await asyncio.sleep(0)  # let run() start waiting
    for hr in (1, 2, 3):
        store.write("I6", minute("a", hr), patient_id="a")
    task.cancel()
    await asyncio.gather(task, return_exceptions=True)
    assert [r["hr"] for r in store.fetch("I6")] == [1, 2, 3]


async def test_a_failing_insert_is_logged_and_later_rows_still_land(tmp_path, monkeypatch, caplog):
    store = Store(tmp_path / "ingest.sqlite")
    real, calls = store._insert, []

    def flaky(batch):
        calls.append(len(batch))
        if len(calls) == 1:
            raise sqlite3.OperationalError("disk full")
        real(batch)

    monkeypatch.setattr(store, "_insert", flaky)
    task = asyncio.create_task(store.run())
    store.write("I6", minute("a", 1), patient_id="a")
    await until(lambda: calls)
    store.write("I6", minute("a", 2), patient_id="a")
    await until(lambda: [r["hr"] for r in store.fetch("I6")] == [2])
    assert not task.done()
    assert "disk full" in caplog.text
    task.cancel()
    await asyncio.gather(task, return_exceptions=True)


def test_full_queue_drops_the_oldest(tmp_path):
    store = Store(tmp_path / "ingest.sqlite", queue_max=2)
    for hr in (1, 2, 3):
        store.write("I6", minute("a", hr), patient_id="a")
    asyncio.run(_run_then_cancel(store))
    assert [r["hr"] for r in store.fetch("I6")] == [2, 3]


async def _run_then_cancel(store):
    task = asyncio.create_task(store.run())
    await asyncio.sleep(0)
    task.cancel()
    await asyncio.gather(task, return_exceptions=True)


async def test_row_columns_carry_time_patient_and_source(tmp_path):
    store = Store(tmp_path / "ingest.sqlite")
    task = asyncio.create_task(store.run())
    await asyncio.sleep(0)  # let run() start waiting
    store.write("I6", minute("a", 70), patient_id="a", source="simulator")
    store.write("I1", VitalsReading(wearable_id=1, ts=T0, hr=72))
    store.write("I7", VitalsReading(wearable_id=1))  # no time field
    task.cancel()
    await asyncio.gather(task, return_exceptions=True)
    con = sqlite3.connect(tmp_path / "ingest.sqlite")
    rows = con.execute("SELECT kind, patient_id, ts, source FROM events ORDER BY id").fetchall()
    assert rows == [
        ("I6", "a", "2026-10-18T09:00:00-07:00", "simulator"),
        ("I1", None, "2026-10-18T09:00:00-07:00", None),
        ("I7", None, None, None),
    ]
