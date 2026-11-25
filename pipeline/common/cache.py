"""Content-addressed file caching keyed by SHA-256 of model inputs."""

from collections.abc import Mapping, Sequence
import hashlib
import json
from pathlib import Path
from typing import Any


def hash_file(path: Path) -> str:
    """Compute and return the SHA-256 hex digest of a file's contents."""
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(65536), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _hash_input_files(
    input_files: Sequence[Path] | Mapping[str, Path] | None,
) -> list[str] | dict[str, str]:
    """Convert input file paths into their SHA-256 digests while preserving order or keys."""
    if input_files is None:
        return []
    if isinstance(input_files, Mapping):
        return {key: hash_file(Path(path)) for key, path in sorted(input_files.items())}
    return [hash_file(Path(path)) for path in input_files]


def build_cache_key(
    model: str,
    prompt: str = "",
    seed: int | None = None,
    params: dict[str, Any] | None = None,
    input_files: Sequence[Path] | Mapping[str, Path] | None = None,
) -> str:
    """Return a SHA-256 cache key from the JSON of all inputs that affect the output."""
    payload: dict[str, Any] = {
        "model": model,
        "prompt": prompt,
        "seed": seed,
        "params": params if params is not None else {},
        "input_files": _hash_input_files(input_files),
    }
    canonical = json.dumps(payload, sort_keys=True, ensure_ascii=False, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def cache_filename(shot_id: str, cache_key: str, ext: str) -> str:
    """Format a cache output filename as <shot_id>_<key[:12]>.<ext>."""
    clean_ext = ext.lstrip(".")
    return f"{shot_id}_{cache_key[:12]}.{clean_ext}"


def cache_path(stage_dir: Path, shot_id: str, cache_key: str, ext: str) -> Path:
    """Return the full output path inside a stage directory for a cached artifact."""
    return stage_dir / cache_filename(shot_id, cache_key, ext)


def get_cached(path: Path) -> Path | None:
    """Return the path if a non-empty cached output already exists, otherwise None."""
    if path.is_file() and path.stat().st_size > 0:
        return path
    return None
