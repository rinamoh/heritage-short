"""Run FFmpeg with one runs.jsonl line per step, plus the shared pause detector."""

from pathlib import Path
import re
import subprocess
import time
from typing import Any

from pipeline.common import config, log

SILENCE_NOISE_DB: float = -40.0
SILENCE_MIN_S: float = 0.25


class FFmpegError(RuntimeError):
    """An FFmpeg step that returned a non-zero exit code."""


def run_ffmpeg(
    args: list[str],
    *,
    stage: str,
    step: str,
    shot_id: str | None = None,
    params: dict[str, Any] | None = None,
    log_path: Path = config.RUNS_LOG_PATH,
    cwd: Path | None = None,
) -> str:
    """Run `ffmpeg <args>`, log the step, and return stderr (where filters print results)."""
    cmd = ["ffmpeg", "-y", "-hide_banner", "-nostats", *args]
    started = time.monotonic()
    proc = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="replace", cwd=cwd)
    error = None if proc.returncode == 0 else proc.stderr.strip()[-800:]
    log.log_call(
        stage=stage,
        shot_id=shot_id,
        provider="ffmpeg",
        model="ffmpeg",
        params={"step": step, **(params or {})},
        latency_s=time.monotonic() - started,
        status="ok" if error is None else "error",
        error=error,
        log_path=log_path,
    )
    if error is not None:
        raise FFmpegError(f"{step}: {error}")
    return proc.stderr


def detect_silences(
    wav: Path,
    *,
    stage: str,
    shot_id: str | None = None,
    log_path: Path = config.RUNS_LOG_PATH,
) -> list[tuple[float, float]]:
    """Return (start, end) of every pause in a WAV, using silencedetect."""
    stderr = run_ffmpeg(
        ["-i", str(wav), "-af", f"silencedetect=noise={SILENCE_NOISE_DB}dB:d={SILENCE_MIN_S}", "-f", "null", "-"],
        stage=stage,
        step="silencedetect",
        shot_id=shot_id,
        params={"file": wav.name},
        log_path=log_path,
    )
    starts = [float(value) for value in re.findall(r"silence_start: (-?[\d.]+)", stderr)]
    ends = [float(value) for value in re.findall(r"silence_end: (-?[\d.]+)", stderr)]
    return list(zip(starts, ends))
