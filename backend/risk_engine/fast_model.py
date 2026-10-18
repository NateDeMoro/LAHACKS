"""Fast trend model (T6 replaces this stub). Use when trend.py asks whether HR, breathing or SpO2
is heading for the danger range within 15 minutes.

The stub has no model: load() is False and predict() is None, so every trend field stays null.
LightGBM is imported only inside load(), so a baseline (no model file) version never needs it."""
import logging
from pathlib import Path

log = logging.getLogger(__name__)

MODEL_PATH = Path(__file__).resolve().parents[2] / "models" / "fast_15.txt"


def load() -> bool:
    """Load the model file if there is one. False means no model (missing file or LightGBM)."""
    if not MODEL_PATH.exists():
        return False
    try:
        import lightgbm  # noqa: F401  (needs libomp on Mac, libgomp on Linux)
    except (ImportError, OSError) as e:
        log.warning("fast trend model off: cannot import lightgbm (%s)", e)
        return False
    return False  # stub: T6 builds the booster here


def predict(history) -> tuple[float, str] | None:
    """Probability of entering the danger range within 15 minutes, and a one-line reason."""
    return None
