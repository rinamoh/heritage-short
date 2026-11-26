"""Assembly stage. For now: the radio cut (narration over a black vertical video)."""

import json
from pathlib import Path
import subprocess
import time

from pipeline.common import config, log
from pipeline.narration import measure_duration_ffprobe
from pipeline.timeline import NARRATION_LEAD_S, ShotTiming, build_timeline

RADIO_WIDTH: int = 1080
RADIO_HEIGHT: int = 1920
AUDIO_RATE: int = 48000
CLICK_FADE_IN_S: float = 0.005
CLICK_FADE_OUT_S: float = 0.01
MIN_TOTAL_S: float = 60.0
MAX_TOTAL_S: float = 90.0
PAD_FREQUENCIES_HZ: tuple[float, ...] = (146.83, 220.0)  # D3 and A3
PAD_VOLUME: float = 0.03
PAD_FADE_S: float = 2.0
MUSIC_VOLUME: float = 0.2
DUCK_SETTINGS: str = "threshold=0.02:ratio=6:attack=20:release=500"


def _voice_filters(timeline: list[ShotTiming], first_input: int) -> list[str]:
    """Build one fixed-length audio track per shot and concatenate them as [voice]."""
    audio_format = f"aformat=sample_fmts=fltp:sample_rates={AUDIO_RATE}:channel_layouts=mono"
    filters: list[str] = []
    input_index = first_input
    for position, shot in enumerate(timeline):
        trim = f"atrim=0:{shot.length_s:.6f},asetpts=PTS-STARTPTS"
        if not shot.segments:
            filters.append(f"anullsrc=r={AUDIO_RATE}:cl=mono,{audio_format},{trim}[a{position}]")
            continue
        labels = ""
        for number, segment in enumerate(shot.segments):
            lead = NARRATION_LEAD_S if number == 0 else 0.0
            delay_ms = round((lead + segment.pause_before_s) * 1000)
            fade_out_start = max(segment.duration_s - CLICK_FADE_OUT_S, 0.0)
            # The fades only remove clicks; the line itself is never shortened.
            filters.append(
                f"[{input_index}:a]{audio_format},afade=t=in:d={CLICK_FADE_IN_S},"
                f"afade=t=out:st={fade_out_start:.6f}:d={CLICK_FADE_OUT_S},"
                f"adelay={delay_ms}:all=1[s{position}_{number}]"
            )
            labels += f"[s{position}_{number}]"
            input_index += 1
        # apad then atrim sets the shot length, which is always past the last segment's end.
        filters.append(f"{labels}concat=n={len(shot.segments)}:v=0:a=1,apad,{trim}[a{position}]")
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


def _music_filters(input_index: int, total_s: float) -> list[str]:
    """Turn the chosen track down, duck it under the narration, and mix both as [mix]."""
    audio_format = f"aformat=sample_fmts=fltp:sample_rates={AUDIO_RATE}:channel_layouts=mono"
    fade_out_start = max(total_s - PAD_FADE_S, 0.0)
    return [
        "[voice]asplit=2[voice_mix][voice_key]",
        f"[{input_index}:a]{audio_format},volume={MUSIC_VOLUME},apad,atrim=0:{total_s:.6f},"
        f"afade=t=out:st={fade_out_start:.6f}:d={PAD_FADE_S}[bed]",
        f"[bed][voice_key]sidechaincompress={DUCK_SETTINGS}[ducked]",
        "[voice_mix][ducked]amix=inputs=2:duration=first:normalize=0[mix]",
    ]


def build_radio_command(
    timeline: list[ShotTiming],
    fps: int,
    out_path: Path,
    music: Path | None = None,
) -> list[str]:
    """Build the single FFmpeg command that renders the radio cut."""
    total_s = sum(shot.length_s for shot in timeline)
    video = f"color=c=black:s={RADIO_WIDTH}x{RADIO_HEIGHT}:r={fps}:d={total_s:.6f}"
    cmd = ["ffmpeg", "-y", "-hide_banner", "-loglevel", "error", "-f", "lavfi", "-i", video]
    inputs = 1
    for shot in timeline:
        for segment in shot.segments:
            cmd += ["-i", str(segment.wav)]
            inputs += 1

    filters = _voice_filters(timeline, first_input=1)
    if music is None:
        filters += _pad_filters(total_s)
        filters.append("[voice][pad]amix=inputs=2:duration=first:normalize=0[mix]")
    else:
        cmd += ["-i", str(music)]
        filters += _music_filters(inputs, total_s)

    cmd += ["-filter_complex", ";".join(filters), "-map", "0:v", "-map", "[mix]"]
    cmd += ["-c:v", "libx264", "-pix_fmt", "yuv420p", "-r", str(fps)]
    cmd += ["-c:a", "aac", "-b:a", "192k", "-ar", str(AUDIO_RATE)]
    cmd += ["-t", f"{total_s:.6f}", "-movflags", "+faststart", str(out_path)]
    return cmd


def _print_timeline(timeline: list[ShotTiming], end_card_s: float) -> None:
    """Print every shot length and the film total, warning if it misses 60-90 s."""
    for shot in timeline:
        kind = f"{len(shot.segments)} segment(s)" if shot.segments else "silent"
        print(f"{shot.shot_id}: {shot.length_s:.2f}s {kind}")
    total_s = sum(shot.length_s for shot in timeline)
    film_s = total_s + end_card_s
    print(f"Shots: {total_s:.2f}s + {end_card_s:.0f}s end card = {film_s:.2f}s")
    if not MIN_TOTAL_S <= film_s <= MAX_TOTAL_S:
        print(f"[WARN] {film_s:.2f}s is outside {MIN_TOTAL_S:.0f}-{MAX_TOTAL_S:.0f}s")


def chosen_track(storyboard: dict) -> Path | None:
    """Return the WAV for music.chosen, or None when no track has been chosen."""
    seed = storyboard["music"].get("chosen")
    if seed is None:
        return None
    path = config.stage_output_dir("music", create=False) / f"music_{seed}.wav"
    if not path.is_file():
        raise FileNotFoundError(f"music.chosen is {seed} but {path} does not exist")
    return path


def run_radio(
    storyboard_path: Path = config.STORYBOARD_PATH,
    log_path: Path = config.RUNS_LOG_PATH,
) -> Path | None:
    """Render outputs/final/radio_cut.mp4, print its length, and return its path."""
    storyboard = json.loads(storyboard_path.read_text(encoding="utf-8"))
    timeline = build_timeline(storyboard, config.stage_output_dir("narration", create=False))
    out_path = config.stage_output_dir("final") / "radio_cut.mp4"
    music = chosen_track(storyboard)
    cmd = build_radio_command(timeline, int(storyboard["output"]["fps"]), out_path, music)
    print(f"Music: {music.name if music else 'placeholder pad'}")

    _print_timeline(timeline, float(storyboard["output"]["end_card_s"]))

    started = time.monotonic()
    proc = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="replace")
    error = None if proc.returncode == 0 else proc.stderr.strip()
    log.log_call(
        stage="radio",
        shot_id=None,
        provider="ffmpeg",
        model="ffmpeg",
        params={
            "shot_lengths_s": {s.shot_id: round(s.length_s, 3) for s in timeline},
            "music": music.name if music else None,
        },
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
