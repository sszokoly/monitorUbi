"""Project TOML configuration loading."""

import tomllib
from pathlib import Path
from typing import Any


DEFAULT_CONFIG_PATH = Path(__file__).resolve().parents[1] / "config.toml"


def load_config(
    config_path: str | Path | None = None,
) -> tuple[dict[str, Any] | None, Path]:
    """Load TOML configuration, returning ``None`` when it is absent."""
    path = Path(config_path or DEFAULT_CONFIG_PATH)
    try:
        with path.open("rb") as config_file:
            config = tomllib.load(config_file)
    except FileNotFoundError:
        return None, path
    except OSError as error:
        raise RuntimeError(f"Unable to read configuration: {path}") from error
    except tomllib.TOMLDecodeError as error:
        raise RuntimeError(f"Invalid TOML configuration: {path}") from error
    return config, path


def get_setting(
    config: dict[str, Any] | None,
    section: str,
    name: str,
    default: Any,
) -> Any:
    """Read an optional named setting while validating its containing section."""
    if config is None:
        return default
    settings = config.get(section, {})
    if not isinstance(settings, dict):
        raise ValueError(f"Configuration section [{section}] must be a table")
    return settings.get(name, default)

if __name__ == "__main__":
    def example():
        config, path = load_config()
        if config is None:
            print(f"No configuration found at {path}")
            return
        print(f"Loaded configuration from {path}:")
        for section, settings in config.items():
            print(f"[{section}]")
            for name, value in settings.items():
                print(f"{name} = {value}")
    
    example()
