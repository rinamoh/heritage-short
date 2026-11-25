"""Structured JSON-lines logging for every model and tool call."""

from datetime import datetime, timezone
import json
from pathlib import Path
from typing import Any

from pipeline.common.config import RUNS_LOG_PATH


def utc_now_iso() -> str:
    """Return the current UTC timestamp formatted as an ISO 8601 string."""
    return datetime.now(timezone.utc).isoformat()


def log_call(
    stage: str,
    shot_id: str | None,
    provider: str,
    model: str,
    params: dict[str, Any] | None = None,
    seed: int | None = None,
    latency_s: float = 0.0,
    cost_usd_equiv: float = 0.0,
    cache_hit: bool = False,
    status: str = "ok",
    error: str | None = None,
    log_path: Path = RUNS_LOG_PATH,
) -> dict[str, Any]:
    """Append one model-call record as a JSON line in runs.jsonl and return it."""
    entry: dict[str, Any] = {
        "ts": utc_now_iso(),
        "stage": stage,
        "shot_id": shot_id,
        "provider": provider,
        "model": model,
        "params": params if params is not None else {},
        "seed": seed,
        "latency_s": round(float(latency_s), 4),
        "cost_usd_equiv": float(cost_usd_equiv),
        "cache_hit": bool(cache_hit),
        "status": status,
        "error": error,
    }
    log_path.parent.mkdir(parents=True, exist_ok=True)
    with log_path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(entry, ensure_ascii=False) + "\n")
    return entry
