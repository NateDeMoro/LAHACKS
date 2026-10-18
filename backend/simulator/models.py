"""Simulator data shapes. A profile is an I2 record plus a fixed-length run script; a run
plays every second of the script as an I1 reading. Key times are fractions of the run so
the length is one setting (config.SimulatorConfig.run_length_s)."""
from dataclasses import dataclass
from typing import Literal, Protocol

from pydantic import model_validator

from backend.contracts import IntakeRecord, MinuteSummary, Model, RunState, VitalsReading

SimVital = Literal["hr", "resp_rate", "spo2", "temp_c"]
SIM_VITALS: tuple[SimVital, ...] = ("hr", "resp_rate", "spo2", "temp_c")
Tier = Literal["healthy", "at_risk", "critical"]
Source = Literal["strap", "simulator"]

# Fractions of the run where expect.news2 is checked: calm, change starts, mid-change, peak.
KEY_FRACTIONS = (0.0, 0.3, 0.6, 1.0)


class Keyframe(Model):
    at: float  # fraction of the run, 0 to 1
    value: float


class Track(Model):
    keyframes: list[Keyframe]  # straight lines between them
    wobble: float = 0  # random offset of up to +/- this, per second
    step: float = 1  # device rounding: 1 for whole numbers, 0.1 for temperature

    @model_validator(mode="after")
    def _ordered(self):
        ats = [k.at for k in self.keyframes]
        if len(ats) < 2 or ats[0] != 0 or ats[-1] != 1 or ats != sorted(set(ats)):
            raise ValueError("keyframes must start at 0, end at 1 and be strictly increasing")
        return self


class Glitch(Model):
    """A short spike or dip that replaces one vital's value, to test persistence windows."""
    vital: SimVital
    at: float  # fraction of the run where it starts
    duration_s: int
    value: float


class Expect(Model):
    news2: list[int]  # total NEWS2 (stream plus the profile's triage points) at each KEY_FRACTIONS
    alerts: str  # the alert behaviour the run should produce, for checking by eye or by a later test

    @model_validator(mode="after")
    def _four(self):
        if len(self.news2) != len(KEY_FRACTIONS):
            raise ValueError("expect.news2 needs one total per key fraction")
        return self


class RunScript(Model):
    tracks: dict[SimVital, Track]
    glitches: list[Glitch] = []
    seed: int
    expect: Expect

    @model_validator(mode="after")
    def _all_vitals(self):
        if set(self.tracks) != set(SIM_VITALS):
            raise ValueError("a run simulates all four vitals")
        return self


class Profile(Model):
    id: str
    name: str
    tier: Tier
    record: IntakeRecord  # the I2 record the intake form is prefilled with
    script: RunScript


@dataclass(frozen=True)
class Sample:
    """One second of simulated vitals."""
    hr: float
    resp_rate: float
    spo2: float
    temp_c: float


class RunSink(Protocol):
    """What a run talks to: ingest's entry function plus run state and the trend history.
    Ingest (S2) and the risk engine implement it; tests and the demo script use fakes."""

    def ingest(self, reading: VitalsReading, source: Source) -> None: ...

    def set_run_state(self, patient_id: str, state: RunState) -> None: ...

    def seed_trend_history(self, patient_id: str, rows: list[MinuteSummary]) -> None: ...
