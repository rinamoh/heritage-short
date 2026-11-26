"""The shot timeline shared by the radio and music stages: narration drives shot lengths."""

from dataclasses import dataclass
import json
import math
from pathlib import Path
import re
from typing import Any

from pipeline.common import cache
from pipeline.narration import build_segment_key, resolve_voice_config, segment_texts

NARRATION_LEAD_S: float = 0.2
DEFAULT_HOLD_AFTER_S: float = 0.6
DEFAULT_MIN_SHOT_S: float = 3.0

# Used only for planning before a line has been recorded.
ESTIMATE_CHARS_PER_S: float = 9.0
ESTIMATE_LONG_PAUSE_S: float = 1.2
INLINE_TAG = re.compile(r"<[^>]*>")


@dataclass(frozen=True)
class RadioSegment:
    """One narration WAV and the pause that precedes it."""

    wav: Path
    duration_s: float
    pause_before_s: float
    estimated: bool = False


@dataclass(frozen=True)
class ShotTiming:
    """One shot on the film timeline."""

    shot_id: str
    length_s: float
    segments: tuple[RadioSegment, ...]
    start_s: float = 0.0


def shot_length(shot: dict[str, Any], segments: tuple[RadioSegment, ...], fps: int) -> float:
    """Apply the timing rule and round up to a whole video frame.

    Narrated: lead + pauses + segment lengths + hold, but never below duration_s.
    Silent: duration_s.
    """
    if segments:
        spoken = sum(segment.pause_before_s + segment.duration_s for segment in segments)
        hold = float(shot.get("hold_after_s", DEFAULT_HOLD_AFTER_S))
        minimum = float(shot.get("duration_s", DEFAULT_MIN_SHOT_S))
        length = max(NARRATION_LEAD_S + spoken + hold, minimum)
    else:
        length = float(shot["duration_s"])
    return math.ceil(round(length * fps, 6)) / fps


def estimate_segment_s(text: str) -> float:
    """Guess how long an unrecorded line will take to speak."""
    pauses = text.count("<long pause>") * ESTIMATE_LONG_PAUSE_S
    return len(INLINE_TAG.sub("", text)) / ESTIMATE_CHARS_PER_S + pauses


def _shot_segments(
    storyboard: dict[str, Any],
    shot: dict[str, Any],
    entry: dict[str, Any],
    narration_dir: Path,
    allow_estimates: bool,
) -> tuple[RadioSegment, ...]:
    """Match a shot's storyboard segments to their rendered WAVs, rejecting stale audio."""
    shot_id = str(shot["id"])
    texts = segment_texts(shot)
    if not texts:
        return ()
    cfg = resolve_voice_config(storyboard, shot)
    rendered = {item["file"]: item for item in entry.get("segments", [])}
    segments: list[RadioSegment] = []
    for number, (text, spec) in enumerate(zip(texts, shot["narration"]["segments"]), start=1):
        key = build_segment_key(text, cfg)[0]
        wav = cache.cache_path(narration_dir, shot_id, key, "wav")
        item = rendered.get(wav.name)
        pause = float(spec.get("pause_before_s", 0.0))
        if item is not None and cache.get_cached(wav) is not None:
            segments.append(RadioSegment(wav, float(item["duration_s"]), pause))
        elif allow_estimates:
            segments.append(RadioSegment(wav, estimate_segment_s(text), pause, estimated=True))
        else:
            raise FileNotFoundError(
                f"{shot_id} segment {number} has no up-to-date narration ({wav.name}). "
                "Run the narration stage first."
            )
    return tuple(segments)


def build_timeline(
    storyboard: dict[str, Any],
    narration_dir: Path,
    allow_estimates: bool = False,
) -> list[ShotTiming]:
    """Return every storyboard shot, in order, with its narration, start time and length."""
    durations_path = narration_dir / "durations.json"
    entries: dict[str, Any] = {}
    if durations_path.is_file() or not allow_estimates:
        entries = json.loads(durations_path.read_text(encoding="utf-8"))["shots"]
    fps = int(storyboard["output"]["fps"])

    timeline: list[ShotTiming] = []
    start_s = 0.0
    for shot in storyboard["shots"]:
        shot_id = str(shot["id"])
        segments = _shot_segments(
            storyboard, shot, entries.get(shot_id) or {}, narration_dir, allow_estimates
        )
        length_s = shot_length(shot, segments, fps)
        timeline.append(ShotTiming(shot_id, length_s, segments, start_s))
        start_s += length_s
    return timeline


def _times_from_pauses(
    cues: list[list[str]],
    begin: float,
    duration_s: float,
    silences: list[tuple[float, float]],
) -> list[tuple[float, float, list[str]]] | None:
    """Split one segment's cues at its longest internal pauses, or None if there are too few."""
    inner = [(start, end) for start, end in silences if start > 0.1 and end < duration_s - 0.1]
    needed = len(cues) - 1
    if len(inner) < needed:
        return None
    gaps = sorted(sorted(inner, key=lambda gap: gap[1] - gap[0], reverse=True)[:needed])
    starts = [0.0] + [end for _, end in gaps]
    ends = [start for start, _ in gaps] + [duration_s]
    return [(round(begin + a, 3), round(begin + b, 3), lines) for a, b, lines in zip(starts, ends, cues)]


def subtitle_cue_times(
    shot: dict[str, Any],
    timing: ShotTiming,
    silences: list[tuple[float, float]] | None = None,
) -> list[tuple[float, float, list[str]]]:
    """Time a shot's subtitle cues inside its spoken narration.

    With the pauses of a single-segment shot, each new cue starts after a pause. Otherwise the
    spoken time is split in proportion to text length.
    """
    cues: list[list[str]] = shot.get("subtitle_en") or []
    if not cues or not timing.segments:
        return []
    begin = timing.start_s + NARRATION_LEAD_S + timing.segments[0].pause_before_s
    if len(cues) > 1 and len(timing.segments) == 1 and silences is not None:
        paused = _times_from_pauses(cues, begin, timing.segments[0].duration_s, silences)
        if paused is not None:
            return paused
        print(f"[WARN] {timing.shot_id}: too few pauses; subtitle cues split by text length")
    spoken = sum(s.duration_s + s.pause_before_s for s in timing.segments)
    span = spoken - timing.segments[0].pause_before_s
    weights = [len(" ".join(lines)) for lines in cues]

    times: list[tuple[float, float, list[str]]] = []
    cursor = begin
    for lines, weight in zip(cues, weights):
        end = cursor + span * weight / sum(weights)
        times.append((round(cursor, 3), round(end, 3), lines))
        cursor = end
    return times
