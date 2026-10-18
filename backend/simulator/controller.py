"""Starts, stops and resets the one active simulated run. The HTTP routes call it now; the I12 handler will once the dashboard socket exists."""
import asyncio
import logging
import time

from backend.config import CONFIG, SimulatorConfig
from backend.contracts import Model, RunState
from backend.simulator.generate import generate, preroll_rows
from backend.simulator.models import Profile, RunSink
from backend.simulator.player import RunPlayer
from backend.simulator.profiles import PROFILES
from backend.timeutil import now_la

log = logging.getLogger(__name__)


class UnknownProfile(KeyError):
    pass


class RunInProgress(RuntimeError):
    pass


class RunStatus(Model):
    state: RunState
    profile_id: str | None = None
    patient_id: str | None = None


class SimController:
    def __init__(self, sink: RunSink, *, cfg: SimulatorConfig = CONFIG.simulator, profiles=PROFILES,
                 now=time.monotonic, sleep=asyncio.sleep, clock=now_la):
        self._sink = sink
        self._cfg = cfg
        self._profiles = profiles
        self._clock = clock
        self._player = RunPlayer(sink, now=now, sleep=sleep)
        self._state: RunState = "live"
        self._profile_id: str | None = None
        self._patient_id: str | None = None
        self._task: asyncio.Task | None = None

    def profiles(self) -> list[Profile]:
        return list(self._profiles.values())

    def profile(self, profile_id: str) -> Profile:
        try:
            return self._profiles[profile_id]
        except KeyError:
            raise UnknownProfile(profile_id) from None

    def status(self) -> RunStatus:
        return RunStatus(state=self._state, profile_id=self._profile_id, patient_id=self._patient_id)

    def start(self, profile_id: str, patient_id: str | None = None, wearable_id: int | None = None,
              length_s: int | None = None) -> RunStatus:
        """Needs a running event loop. Without a patient_id the sample's own id is used, for use before intake exists."""
        profile = self.profile(profile_id)
        if self._state == "running":
            raise RunInProgress(self._profile_id)
        patient_id = patient_id or profile.record.patient_id
        start_ts = self._clock()
        # Built before any state changes, so a bad length cannot leave the controller stuck as running.
        samples = generate(profile.script, length_s if length_s is not None else self._cfg.run_length_s)
        preroll = preroll_rows(profile.script, patient_id, start_ts, self._cfg.preroll_minutes)
        task = asyncio.create_task(self._run(
            patient_id=patient_id,
            wearable_id=wearable_id if wearable_id is not None else self._cfg.default_wearable_id,
            start_ts=start_ts, samples=samples, preroll=preroll,
        ))
        task.add_done_callback(self._finish)
        self._profile_id, self._patient_id, self._task, self._state = profile_id, patient_id, task, "running"
        return self.status()

    async def wait(self) -> None:
        if self._task:
            await asyncio.wait([self._task])

    async def stop(self) -> RunStatus:
        task = self._task
        if task and not task.done():
            task.cancel()
            await asyncio.wait([task])
            self._finish(task)  # a run cancelled before its first step never reaches the player's own ending
        return self.status()

    async def reset(self) -> RunStatus:
        task, patient_id = self._task, self._patient_id
        await self.stop()
        if self._task is task:  # a start that landed while stop was finishing must not be wiped
            if patient_id:
                self._sink.set_run_state(patient_id, "live")
            self._state, self._profile_id, self._patient_id, self._task = "live", None, None, None
        return self.status()

    def _finish(self, task: asyncio.Task) -> None:
        if self._task is task:
            self._state = "ended"

    async def _run(self, **play_args) -> None:
        try:
            await self._player.play(**play_args)
        except Exception:
            log.exception("simulated run failed")
