"""Central config, one section per component. Defaults live here; machine-specific
values (wearable, ingest URL, strap name) come from environment variables so they
can sit in .env. Run with `uv run --env-file .env ...` to load it."""
import os
from dataclasses import dataclass, field
from pathlib import Path


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
class AdjusterConfig:
    """Context adjuster (B3). logs/ is gitignored: quotes come from patient complaints."""
    log_path: Path = Path(__file__).resolve().parents[1] / "logs" / "adjuster_log.jsonl"  # I15 evaluation log
    cache_path: Path = Path(__file__).resolve().parents[1] / "logs" / "adjuster_cache.json"
    use_cache: bool = True
    write_log: bool = True
    parallelism: int = 3  # scoring concurrency; the lowest StepFun tier allows 5


@dataclass(frozen=True)
class ConditionsConfig:
    """Custom conditions and drafted rules. logs/ is gitignored: evidence holds condition names."""
    enabled: bool = True  # kill switch for drafted rules; the lookup and checklist mapping stay on
    allowed_vitals: tuple[str, ...] = ("hr", "resp_rate", "spo2", "temp_c")  # sbp is a triage reading, never graded
    normalize_enabled: bool = True  # fallback rewrite of a term the vocabulary did not find
    min_sources: int = 2  # distinct sources that must support a pick
    match_threshold: float = 0.85  # fuzzy match score for a typed term against the vocabulary
    max_abstracts: int = 8
    nlm_timeout_s: float = 8.0
    pubmed_timeout_s: float = 10.0
    menu_path: Path = Path(__file__).resolve().parents[1] / "models" / "limit_menu.json"
    store_path: Path = Path(__file__).resolve().parents[1] / "logs" / "condition_store.json"  # frozen evidence
    log_path: Path = Path(__file__).resolve().parents[1] / "logs" / "condition_log.jsonl"


@dataclass(frozen=True)
class BedConfig:
    """Bed label per wearable, used in alert messages."""
    labels: dict[int, str] = field(default_factory=lambda: {1: "Polar H10", 101: "Wearable 1", 102: "Wearable 2",
                                                             103: "Wearable 3", 104: "Wearable 4", 105: "Wearable 5",
                                                             106: "Wearable 6"})


@dataclass(frozen=True)
class SimulatorConfig:
    run_length_s: int = 600  # every run script is stored as fractions of this, so changing it rescales all six
    preroll_minutes: int = 60  # trend-model look-back fed before 0:00; matches trend.HISTORY
    default_wearable_id: int = ReceiverConfig.wearable_id  # same wearer as the strap
    scenario_wearable_ids: tuple[int, ...] = (101, 102, 103, 104, 105, 106)  # the waiting room's sim wearables, in patient order


@dataclass(frozen=True)
class IngestConfig:
    """Ingest service (S2). Times in seconds."""
    window_s: float = 30.0  # rolling window for I13 (so NEWS2) and length of an I6 period
    sim_ttl_s: float = 5.0  # a simulator value stays current this long (live-mode merge)
    strap_ttl_s: float = 3.0  # a strap reading stays current this long; the strap sends about once a second
    min_samples: int = 5  # clean seconds a vital needs in the window before I13 reports a median
    bounds: dict[str, tuple[float, float]] = field(default_factory=lambda: {  # impossible values only; danger must pass
        "hr": (20, 250), "resp_rate": (3, 60), "spo2": (50, 100), "temp_c": (30, 45)})
    default_assignments: dict[int, str] = field(default_factory=lambda: {ReceiverConfig.wearable_id: "demo-001"})
    store_path: str = os.environ.get("INGEST_STORE_PATH", "data/ingest.sqlite")
    unassigned_log_every_s: float = 30.0
    disabled_vitals: tuple[str, ...] = ()  # breathing re-enabled for the demo (was ("resp_rate",)); list a vital here to drop it from both sources


@dataclass(frozen=True)
class Config:
    receiver: ReceiverConfig = field(default_factory=ReceiverConfig)
    beds: BedConfig = field(default_factory=BedConfig)
    llm: LlmConfig = field(default_factory=LlmConfig)
    adjuster: AdjusterConfig = field(default_factory=AdjusterConfig)
    conditions: ConditionsConfig = field(default_factory=ConditionsConfig)
    simulator: SimulatorConfig = field(default_factory=SimulatorConfig)
    ingest: IngestConfig = field(default_factory=IngestConfig)


CONFIG = Config()
