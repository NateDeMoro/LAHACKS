"""Central config, one section per component. Defaults live here; machine-specific
values (wearable, ingest URL, strap name) come from environment variables so they
can sit in .env. Run with `uv run --env-file .env ...` to load it."""
import os
from dataclasses import dataclass, field


@dataclass(frozen=True)
class BreathingConfig:
    """Breathing rate from beat intervals. Values tuned on synthetic data; recheck on the strap."""
    window_s: float = 60.0
    resample_hz: float = 4.0
    nfft: int = 4096
    bandpass_hz: tuple[float, float] = (0.05, 0.7)  # wider than the search band so its edges aren't dulled
    search_hz: tuple[float, float] = (0.08, 0.5)  # about 5-30 breaths/min
    min_beats: int = 20  # also at least window_s / 3
    max_gap_s: float = 5.0
    skip_tolerance: float = 0.2  # beat interval this far off its 7-beat median is replaced by the median
    peak_ratio: float = 3.0  # peak must beat the strongest competing peak by this factor
    band_power_frac: float = 0.4  # share of search-band power within +-0.03 Hz of the peak
    hr_guard: float = 0.45  # no value if the peak is above this x heart rate (aliasing)


@dataclass(frozen=True)
class ReceiverConfig:
    wearable_id: int = int(os.environ.get("RECEIVER_WEARABLE_ID", "1"))
    ingest_url: str = os.environ.get("RECEIVER_INGEST_URL", "ws://localhost:8000/ws/ingest")
    strap_name_prefix: str = os.environ.get("RECEIVER_STRAP_NAME_PREFIX", "Polar H10")
    scan_timeout_s: float = 10.0
    reconnect_backoff_s: tuple[float, float] = (1.0, 15.0)  # first and maximum wait between tries
    stall_timeout_s: float = 10.0  # connected but no frames for this long counts as down
    no_beat_timeout_s: float = 5.0  # no beats for this long means no contact when the strap has no contact flag
    breathing: BreathingConfig = field(default_factory=BreathingConfig)


@dataclass(frozen=True)
class LlmConfig:
    """StepFun through its OpenAI-compatible endpoint. Key, URL and model come from .env."""
    api_key: str = os.environ.get("STEPFUN_API_KEY", "")
    base_url: str = os.environ.get("STEPFUN_BASE_URL", "https://api.stepfun.ai/v1")
    model: str = os.environ.get("STEPFUN_MODEL", "step-5-preview")
    timeout_s: float = 120.0  # a call takes 25-45 s even at low reasoning effort
    max_tokens: int = 8000  # reasoning tokens count too (about 3-4.5k per call); a cut-off reply is a failure
    temperature: float = 0.0
    reasoning_effort: str = "low"


@dataclass(frozen=True)
class Config:
    receiver: ReceiverConfig = field(default_factory=ReceiverConfig)
    llm: LlmConfig = field(default_factory=LlmConfig)


CONFIG = Config()
