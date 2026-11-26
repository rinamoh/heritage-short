"""Shots stage: one cached video clip per shot (Ken Burns, or a finished Wan clip)."""

from dataclasses import dataclass
import json
from pathlib import Path
from typing import Any

from pipeline import keyframes
from pipeline.common import cache, config, ffmpeg, log
from pipeline.timeline import ShotTiming, build_timeline

STAGE: str = "shots"
WIDTH: int = 1080
HEIGHT: int = 1920
ZOOM_MAX: float = 1.12
# zoompan moves its window in whole pixels; a larger source makes those steps invisible.
UPSCALE: int = 4
# Every clip runs this much past its shot, so a dissolve never moves the next shot's start.
DISSOLVE_S: float = 0.5
INTERMEDIATE_CODEC: tuple[str, ...] = ("-c:v", "libx264", "-preset", "medium", "-crf", "14", "-pix_fmt", "yuv420p")

WAN_MODEL: str = "Wan2.2-TI2V-5B"
WAN_SIZE: str = "704x1280"


@dataclass(frozen=True)
class Clip:
    """The video chosen for one shot."""

    shot_id: str
    path: Path
    used_wan: bool


def clip_frames(timing: ShotTiming, fps: int) -> int:
    """Return the clip length in frames: the shot's timeline length plus the dissolve."""
    return round(timing.length_s * fps) + round(DISSOLVE_S * fps)


def zoompan_filter(direction: str, frames: int, fps: int) -> str:
    """Build the Ken Burns filter chain for one still image."""
    progress = f"on/{max(frames - 1, 1)}"
    travel = ZOOM_MAX - 1.0
    centre_x, centre_y = "(iw-iw/zoom)/2", "(ih-ih/zoom)/2"
    moves: dict[str, tuple[str, str]] = {
        "in": (f"1+{travel:.4f}*{progress}", centre_x),
        "out": (f"{ZOOM_MAX}-{travel:.4f}*{progress}", centre_x),
        "right": (str(ZOOM_MAX), f"(iw-iw/zoom)*{progress}"),
        "left": (str(ZOOM_MAX), f"(iw-iw/zoom)*(1-{progress})"),
    }
    zoom, x = moves[direction]
    big_w, big_h = WIDTH * UPSCALE, HEIGHT * UPSCALE
    return (
        f"scale={big_w}:{big_h}:force_original_aspect_ratio=increase:flags=lanczos,"
        f"crop={big_w}:{big_h},format=yuv444p,"
        f"zoompan=z='{zoom}':x='{x}':y='{centre_y}':d={frames}:s={WIDTH}x{HEIGHT}:fps={fps},"
        "setsar=1,format=yuv420p"
    )


def still_filter() -> str:
    """Build the filter for a motionless clip (the fallback)."""
    return (
        f"scale={WIDTH}:{HEIGHT}:force_original_aspect_ratio=increase:flags=lanczos,"
        f"crop={WIDTH}:{HEIGHT},setsar=1,format=yuv420p"
    )


def wan_source_path(shot: dict[str, Any], keyframe: Path, shots_dir: Path) -> Path:
    """Return where a Wan clip for this shot is expected: outputs/shots/wan/<shot>_<key>.mp4."""
    key = cache.build_cache_key(
        WAN_MODEL,
        prompt=shot["motion"]["prompt"],
        seed=int(shot["motion"]["seed"]),
        params={"size": WAN_SIZE},
        input_files=[keyframe],
    )
    return cache.cache_path(shots_dir / "wan", shot["id"], key, "mp4")


def _render(
    out_path: Path,
    args: list[str],
    shot_id: str,
    params: dict[str, Any],
    log_path: Path,
) -> None:
    """Render a clip into a temporary name first, so a failed run is never mistaken for a cache hit."""
    partial = out_path.with_name(f"{out_path.stem}.part.mp4")
    ffmpeg.run_ffmpeg(
        [*args, str(partial)],
        stage=STAGE,
        step=params["step"],
        shot_id=shot_id,
        params={**params, "output": out_path.name},
        log_path=log_path,
    )
    partial.replace(out_path)


def _cached_or_rendered(
    out_path: Path,
    args: list[str],
    shot_id: str,
    params: dict[str, Any],
    log_path: Path,
) -> Path:
    """Reuse an existing clip (logged as a cache hit) or render it."""
    if cache.get_cached(out_path) is not None:
        log.log_call(
            stage=STAGE,
            shot_id=shot_id,
            provider="ffmpeg",
            model="ffmpeg",
            params={**params, "output": out_path.name},
            cache_hit=True,
            log_path=log_path,
        )
        print(f"[CACHED] {shot_id}: {out_path.name}")
        return out_path
    _render(out_path, args, shot_id, params, log_path)
    print(f"[OK] {shot_id}: {out_path.name}")
    return out_path


def _wan_clip(source: Path, shot_id: str, frames: int, fps: int, out_dir: Path, log_path: Path) -> Path:
    """Fit a Wan clip to the film's size and the shot's length, holding its last frame if short."""
    params = {"step": "wan_fit", "frames": frames, "fps": fps, "size": f"{WIDTH}x{HEIGHT}"}
    key = cache.build_cache_key("ffmpeg-wan-fit", params=params, input_files=[source])
    video = f"fps={fps},{still_filter()},tpad=stop_mode=clone:stop_duration={frames / fps:.6f}"
    args = ["-i", str(source), "-vf", video, "-an", "-frames:v", str(frames), *INTERMEDIATE_CODEC, "-r", str(fps)]
    return _cached_or_rendered(cache.cache_path(out_dir, shot_id, key, "mp4"), args, shot_id, params, log_path)


def _kenburns_clip(
    shot: dict[str, Any],
    keyframe: Path,
    frames: int,
    fps: int,
    out_dir: Path,
    log_path: Path,
) -> Path:
    """Make the Ken Burns clip; if FFmpeg fails, fall back to a still of the keyframe."""
    shot_id = shot["id"]
    direction = shot["motion"]["kb_direction"]
    video = zoompan_filter(direction, frames, fps)
    params = {"step": "kenburns", "direction": direction, "frames": frames, "fps": fps}
    key = cache.build_cache_key(
        "ffmpeg-kenburns", params={**params, "filter": video, "codec": INTERMEDIATE_CODEC}, input_files=[keyframe]
    )
    out_path = cache.cache_path(out_dir, shot_id, key, "mp4")
    codec = [*INTERMEDIATE_CODEC, "-r", str(fps), "-frames:v", str(frames)]
    try:
        return _cached_or_rendered(out_path, ["-i", str(keyframe), "-vf", video, *codec], shot_id, params, log_path)
    except ffmpeg.FFmpegError as exc:
        print(f"[FAIL] {shot_id}: {exc}\n[FALLBACK] {shot_id}: using a still frame")
        # A different name, so the next run tries the motion again.
        fallback = out_path.with_name(f"{out_path.stem}_still.mp4")
        args = ["-loop", "1", "-framerate", str(fps), "-i", str(keyframe), "-vf", still_filter(), *codec]
        _render(fallback, args, shot_id, {**params, "step": "still_fallback"}, log_path)
        return fallback


def render_shots(
    storyboard: dict[str, Any],
    timeline: list[ShotTiming],
    log_path: Path = config.RUNS_LOG_PATH,
) -> list[Clip]:
    """Return one clip per shot, in order, rendering only what is not cached."""
    frames_by_shot = {timing.shot_id: timing for timing in timeline}
    fps = int(storyboard["output"]["fps"])
    stills = keyframes.current_keyframes(storyboard)
    out_dir = config.stage_output_dir(STAGE)

    clips: list[Clip] = []
    for shot in storyboard["shots"]:
        shot_id = shot["id"]
        frames = clip_frames(frames_by_shot[shot_id], fps)
        if shot["motion"]["method"] == "wan":
            source = wan_source_path(shot, stills[shot_id], out_dir)
            if cache.get_cached(source) is not None:
                try:
                    path = _wan_clip(source, shot_id, frames, fps, out_dir, log_path)
                    clips.append(Clip(shot_id, path, used_wan=True))
                    continue
                except ffmpeg.FFmpegError as exc:
                    print(f"[FAIL] {shot_id}: {exc}\n[FALLBACK] {shot_id}: using Ken Burns")
            else:
                print(f"[FALLBACK] {shot_id}: no Wan clip at {source}; using Ken Burns")
        path = _kenburns_clip(shot, stills[shot_id], frames, fps, out_dir, log_path)
        clips.append(Clip(shot_id, path, used_wan=False))
    return clips


def run_shots(
    storyboard_path: Path = config.STORYBOARD_PATH,
    log_path: Path = config.RUNS_LOG_PATH,
) -> list[Clip]:
    """Render every shot clip from the storyboard and the narration timeline."""
    storyboard = json.loads(storyboard_path.read_text(encoding="utf-8"))
    timeline = build_timeline(storyboard, config.stage_output_dir("narration", create=False))
    return render_shots(storyboard, timeline, log_path)
