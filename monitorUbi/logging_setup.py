"""Configure Loguru sinks from the project's external YAML file."""

import os
import sys
from pathlib import Path
from typing import Any, Literal, Optional

import yaml
from loguru import logger


LoggingMode = Literal["tui", "headless"]
DEFAULT_CONFIG_PATH = Path(__file__).resolve().parents[1] / "logging.yaml"


def configure_logging(
    mode: LoggingMode, config_path: Optional[str | Path] = None
) -> list[int]:
    """Replace Loguru's default sink with handlers enabled for the given mode."""
    path = Path(config_path or os.getenv("MONITORUBI_LOG_CONFIG", DEFAULT_CONFIG_PATH))
    try:
        config = yaml.safe_load(path.read_text(encoding="utf-8"))
    except OSError as error:
        raise RuntimeError(f"Unable to read logging configuration: {path}") from error
    except yaml.YAMLError as error:
        raise RuntimeError(f"Invalid logging configuration: {path}") from error

    handlers = config.get("handlers") if isinstance(config, dict) else None
    if not isinstance(handlers, list):
        raise ValueError("Logging configuration must define a handlers list")

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
