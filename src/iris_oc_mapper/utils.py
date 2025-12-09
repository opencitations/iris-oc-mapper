import logging
from pathlib import Path

import polars as pl

TRACE_LEVEL = 5
logging.addLevelName(TRACE_LEVEL, "TRACE")


def trace(self, message, *args, **kwargs):
    if self.isEnabledFor(TRACE_LEVEL):
        self._log(TRACE_LEVEL, message, args, **kwargs)


class TraceLogger(logging.Logger):
    def trace(self, msg, *args, **kwargs):
        if self.isEnabledFor(TRACE_LEVEL):
            self.log(TRACE_LEVEL, msg, *args, **kwargs)


logging.setLoggerClass(TraceLogger)


def setup_logging(debug: bool = False, trace: bool = False) -> TraceLogger:
    """Setup root logger.

    Args:
        debug (bool): Enable debug logging.
        trace (bool): Enable trace logging.

    Returns:
        TraceLogger: Configured logger instance.
    """

    if trace:
        log_level = TRACE_LEVEL
    elif debug:
        log_level = logging.DEBUG
    else:
        log_level = logging.INFO

    logging.basicConfig(
        level=log_level,
        format="%(asctime)s.%(msecs)03d - %(name)s - %(levelname)s - %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    return logging.getLogger(__name__)  # type: ignore[return-value]


def get_logger(name: str) -> TraceLogger:
    return logging.getLogger(name)  # type: ignore[return-value]


def load_translations() -> dict[str, str]:
    """Load IRIS types translations from CSV file.

    Returns:
        dict[str, str]: Dictionary mapping Italian terms to English terms.
    """
    RESOURCES_DIR = Path(__file__).parent / "datasets" / "resources"
    translations_file = RESOURCES_DIR / "iris_types_translations.csv"

    try:
        df = pl.read_csv(
            translations_file.open("rb"),
            separator=";",
            encoding="utf8",
            has_header=True,
        )
    except FileNotFoundError:
        raise FileNotFoundError("Translations file not found.")

    return {it: en for it, en in df.iter_rows()}
