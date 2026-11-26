"""Assembly stage. For now: the radio cut (narration over a black vertical video)."""

from dataclasses import dataclass
import json
import math
from pathlib import Path
import subprocess
import time
from typing import Any

from pipeline.common import config, log
from pipeline.narration import measure_duration_ffprobe

RADIO_WIDTH: int = 1080
RADIO_HEIGHT: int = 1920
AUDIO_RATE: int = 48000
NARRATION_PADDING_S: float = 0.6
NARRATION_LEAD_S: float = 0.3
PAD_FREQUENCIES_HZ: tuple[float, ...] = (146.83, 220.0)  # D3 and A3
PAD_VOLUME: float = 0.03
PAD_FADE_S: float = 2.0


@dataclass(frozen=True)
class RadioShot:
    """One shot on the radio-cut timeline."""

    shot_id: str
    length_s: float
    wav: Path | None


def shot_length(planned_s: float, narration_s: float | None, fps: int) -> float:
    """Return max(planned, narration + padding), rounded up to a whole video frame."""
    length = float(planned_s)
    if narration_s is not None:
        length = max(length, narration_s + NARRATION_PADDING_S)
    return math.ceil(round(length * fps, 6)) / fps


def build_timeline(storyboard: dict[str, Any], narration_dir: Path) -> list[RadioShot]:
    """Pair every storyboard shot, in order, with its narration WAV and screen time."""
    durations_path = narration_dir / "durations.json"
    entries = json.loads(durations_path.read_text(encoding="utf-8"))["shots"]
    fps = int(storyboard["output"]["fps"])

    timeline: list[RadioShot] = []
    for shot in storyboard["shots"]:
        shot_id = str(shot["id"])
        text = str((shot.get("narration") or {}).get("text_am") or "").strip()
        wav: Path | None = None
        narration_s: float | None = None
        if text:
            entry = entries.get(shot_id)
            if entry is None:
                raise ValueError(f"{shot_id} has narration text but no entry in {durations_path}")
            wav = narration_dir / entry["file"]
            if not wav.is_file():
                raise FileNotFoundError(f"Missing narration file for {shot_id}: {wav}")
            narration_s = float(entry["duration_s"])
        timeline.append(RadioShot(shot_id, shot_length(shot["duration_s"], narration_s, fps), wav))
    return timeline


def _voice_filters(timeline: list[RadioShot], first_input: int) -> list[str]:
    """Build one fixed-length audio segment per shot and concatenate them as [voice]."""
    audio_format = f"aformat=sample_fmts=fltp:sample_rates={AUDIO_RATE}:channel_layouts=mono"
    lead_ms = round(NARRATION_LEAD_S * 1000)
    filters: list[str] = []
    input_index = first_input
    for position, shot in enumerate(timeline):
        trim = f"atrim=0:{shot.length_s:.6f},asetpts=PTS-STARTPTS"
        if shot.wav is None:
            filters.append(f"anullsrc=r={AUDIO_RATE}:cl=mono,{audio_format},{trim}[a{position}]")
            continue
        filters.append(
            f"[{input_index}:a]{audio_format},adelay={lead_ms}:all=1,apad,{trim}[a{position}]"
        )
        input_index += 1
    labels = "".join(f"[a{position}]" for position in range(len(timeline)))
    # Loudness is set on the voice alone, so the pad is not boosted during silent shots.
    filters.append(
        f"{labels}concat=n={len(timeline)}:v=0:a=1,"
        f"loudnorm=I=-14:TP=-1,aresample={AUDIO_RATE},{audio_format}[voice]"
    )
    return filters


def _pad_filters(total_s: float) -> list[str]:
    """Synthesize a very quiet two-note placeholder pad as [pad]."""
    labels = ""
    filters: list[str] = []
    for index, frequency in enumerate(PAD_FREQUENCIES_HZ):
        filters.append(f"sine=frequency={frequency}:sample_rate={AUDIO_RATE}:duration={total_s:.6f}[p{index}]")
        labels += f"[p{index}]"
    fade_out_start = max(total_s - PAD_FADE_S, 0.0)
    filters.append(
        f"{labels}amix=inputs={len(PAD_FREQUENCIES_HZ)}:normalize=0,volume={PAD_VOLUME},"
        f"afade=t=in:d={PAD_FADE_S},afade=t=out:st={fade_out_start:.6f}:d={PAD_FADE_S},"
        f"aformat=sample_fmts=fltp:sample_rates={AUDIO_RATE}:channel_layouts=mono[pad]"
    )
    return filters


def build_radio_command(timeline: list[RadioShot], fps: int, out_path: Path) -> list[str]:
    """Build the single FFmpeg command that renders the radio cut."""
    total_s = sum(shot.length_s for shot in timeline)
    video = f"color=c=black:s={RADIO_WIDTH}x{RADIO_HEIGHT}:r={fps}:d={total_s:.6f}"
    cmd = ["ffmpeg", "-y", "-hide_banner", "-loglevel", "error", "-f", "lavfi", "-i", video]
    for shot in timeline:
        if shot.wav is not None:
            cmd += ["-i", str(shot.wav)]

    filters = _voice_filters(timeline, first_input=1) + _pad_filters(total_s)
    filters.append("[voice][pad]amix=inputs=2:duration=first:normalize=0[mix]")

    cmd += ["-filter_complex", ";".join(filters), "-map", "0:v", "-map", "[mix]"]
    cmd += ["-c:v", "libx264", "-pix_fmt", "yuv420p", "-r", str(fps)]
    cmd += ["-c:a", "aac", "-b:a", "192k", "-ar", str(AUDIO_RATE)]
    cmd += ["-t", f"{total_s:.6f}", "-movflags", "+faststart", str(out_path)]
    return cmd


def run_radio(
    storyboard_path: Path = config.STORYBOARD_PATH,
    log_path: Path = config.RUNS_LOG_PATH,
) -> Path | None:
    """Render outputs/final/radio_cut.mp4, print its length, and return its path."""
    storyboard = json.loads(storyboard_path.read_text(encoding="utf-8"))
    timeline = build_timeline(storyboard, config.stage_output_dir("narration", create=False))
    out_path = config.stage_output_dir("final") / "radio_cut.mp4"
    cmd = build_radio_command(timeline, int(storyboard["output"]["fps"]), out_path)

    for shot in timeline:
        print(f"{shot.shot_id}: {shot.length_s:.2f}s {'narration' if shot.wav else 'silent'}")

    started = time.monotonic()
    proc = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="replace")
    error = None if proc.returncode == 0 else proc.stderr.strip()
    log.log_call(
        stage="radio",
        shot_id=None,
        provider="ffmpeg",
        model="ffmpeg",
        params={"shot_lengths_s": {s.shot_id: round(s.length_s, 3) for s in timeline}},
        latency_s=time.monotonic() - started,
        status="ok" if error is None else "error",
        error=error,
        log_path=log_path,
    )
    if error is not None:
        print(f"[FAIL] radio cut: {error}")
        return None

    print(f"[OK] {out_path} (total length: {measure_duration_ffprobe(out_path):.2f}s)")
    return out_path
