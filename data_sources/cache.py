from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

CACHE_DIR = Path("cache")
CACHE_TTL = timedelta(days=1)


def configure_cache(
    cache_dir: str | Path | None = None,
    cache_ttl: timedelta | None = None,
) -> None:
    global CACHE_DIR, CACHE_TTL
    if cache_dir is not None:
        CACHE_DIR = Path(cache_dir)
    if cache_ttl is not None:
        CACHE_TTL = cache_ttl


def _cache_path(key: str, cache_dir: str | Path | None = None) -> Path:
    digest = hashlib.sha256(key.encode("utf-8")).hexdigest()[:16]
    safe_key = "".join(char if char.isalnum() or char in "-_" else "_" for char in key)
    return Path(cache_dir or CACHE_DIR) / f"{safe_key[:80]}_{digest}.json"


def load_from_cache(
    key: str,
    max_age: timedelta | None = None,
    cache_dir: str | Path | None = None,
    no_cache: bool = False,
) -> dict[str, Any] | None:
    if no_cache:
        return None
    path = _cache_path(key, cache_dir=cache_dir)
    if not path.exists():
        return None
    if max_age is not None:
        modified_at = datetime.fromtimestamp(path.stat().st_mtime, tz=UTC)
        if datetime.now(UTC) - modified_at > max_age:
            return None
    with path.open("r", encoding="utf-8") as file:
        return json.load(file)


def save_to_cache(
    key: str,
    data: dict[str, Any],
    cache_dir: str | Path | None = None,
    no_cache: bool = False,
) -> None:
    if no_cache:
        return
    resolved_cache_dir = Path(cache_dir or CACHE_DIR)
    resolved_cache_dir.mkdir(parents=True, exist_ok=True)
    path = _cache_path(key, cache_dir=resolved_cache_dir)
    with path.open("w", encoding="utf-8") as file:
        json.dump(data, file, ensure_ascii=False, indent=2, sort_keys=True)
