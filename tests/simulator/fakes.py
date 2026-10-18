class FakeSink:
    """Records every call a run makes, in order."""

    def __init__(self, clock=None, ingest_cost=0.0):
        self.calls = []
        self._clock = clock
        self._cost = ingest_cost

    def ingest(self, reading, source):
        self.calls.append(("ingest", reading, source))
        if self._clock:
            self._clock.t += self._cost

    def assign(self, wearable_id, patient_id):
        self.calls.append(("assign", wearable_id, patient_id))

    def set_run_state(self, patient_id, state):
        self.calls.append(("state", patient_id, state))

    def seed_trend_history(self, patient_id, rows):
        self.calls.append(("seed", patient_id, rows))

    def readings(self):
        return [c[1] for c in self.calls if c[0] == "ingest"]

    def states(self):
        return [c[2] for c in self.calls if c[0] == "state"]
