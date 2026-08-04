"""Configure Loguru sinks from project TOML configuration."""

import sys
from pathlib import Path
from typing import Any, Literal

from loguru import logger

from monitorUbi.config import get_setting, load_config


LoggingMode = Literal["tui", "headless"]
DEFAULT_HANDLERS = [
    {
        "sink": "ext://sys.stderr",
        "modes": ["headless"],
        "format": "{time:YYYY-MM-DD HH:mm:ss} | <level>{level:<8}</level> | {message}",
        "level": "INFO",
        "colorize": True,
    },
    {
        "sink": "app.log",
        "modes": ["tui", "headless"],
        "format": "{time:YYYY-MM-DD HH:mm:ss} | {level:<8} | {function:<15} | {line:<3} | {message}",
        "level": "INFO",
        "rotation": 2048000,
        "retention": 3,
        "backtrace": False,
        "diagnose": False,
    },
]


def configure_logging(
    mode: LoggingMode, config_path: str | Path | None = None
) -> list[int]:
    """Replace Loguru's default sink with TOML handlers for the given mode."""
    config, path = load_config(config_path)
    handlers = get_setting(config, "logging", "handlers", DEFAULT_HANDLERS)
    if not isinstance(handlers, list):
        raise ValueError("Configuration logging.handlers must be an array")

    logger.remove()
    sink_ids: list[int] = []
    for handler in handlers:
        if not isinstance(handler, dict):
            raise ValueError("Each logging handler must be a mapping")

        options = handler.copy()
        modes = options.pop("modes", ["tui", "headless"])
        if mode not in modes:
            continue

        sink = _resolve_sink(options.pop("sink", None), path.parent)
        sink_ids.append(logger.add(sink, **options))

    if not sink_ids:
        raise ValueError(f"No logging handlers are enabled for mode: {mode}")
    return sink_ids


def _resolve_sink(sink: Any, config_directory: Path) -> Any:
    """Resolve streams and file paths that YAML cannot represent directly."""
    if sink == "ext://sys.stderr":
        return sys.stderr
    if sink == "ext://sys.stdout":
        return sys.stdout
    if isinstance(sink, str):
        path = Path(sink)
        if not path.is_absolute():
            path = config_directory / path
        path.parent.mkdir(parents=True, exist_ok=True)
        return path
    raise ValueError("Logging handler sink must be a stream alias or file path")
