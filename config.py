from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any

_load_dotenv: Any
try:
    from dotenv import load_dotenv as _load_dotenv
except ImportError:  # pragma: no cover - dependency is declared
    _load_dotenv = None

load_dotenv: Any = _load_dotenv


ENV_PATH = Path(".env")


@dataclass(frozen=True)
class Settings:
    the_odds_api_key: str | None = None
    football_data_api_key: str | None = None
    api_football_key: str | None = None


def _load_env_file_fallback(env_path: str | Path) -> None:
    path = Path(env_path)
    if not path.exists():
        return

    with path.open("r", encoding="utf-8") as file:
        for line in file:
            stripped = line.strip()
            if not stripped or stripped.startswith("#") or "=" not in stripped:
                continue

            key, value = stripped.split("=", 1)
            key = key.strip()
            if key.startswith("export "):
                key = key.removeprefix("export ").strip()
            if not key or key in os.environ:
                continue

            os.environ[key] = value.strip().strip("\"'")


def load_settings(env_path: str | Path = ENV_PATH) -> Settings:
    if load_dotenv is not None:
        load_dotenv(env_path)
    else:
        _load_env_file_fallback(env_path)

    return Settings(
        the_odds_api_key=os.getenv("THE_ODDS_API_KEY") or None,
        football_data_api_key=os.getenv("FOOTBALL_DATA_API_KEY") or None,
        api_football_key=os.getenv("API_FOOTBALL_KEY") or None,
    )


def require_api_key(name: str, value: str | None) -> str:
    if not value:
        raise ValueError(
            f"{name} fehlt. Trage den Key in .env ein oder nutze "
            "manuelle CLI-Parameter."
        )
    return value
