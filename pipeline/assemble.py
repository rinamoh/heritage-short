"""Assembly: the radio cut (narration over black) and the finished film in 9:16 and 16:9."""

import json
from pathlib import Path
import re
import subprocess
import time
from typing import Any

from PIL import Image, ImageDraw, ImageFont

from pipeline import shots
from pipeline.common import config, ffmpeg, log
from pipeline.narration import measure_duration_ffprobe
from pipeline.timeline import NARRATION_LEAD_S, ShotTiming, build_timeline, subtitle_cue_times

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

FILM_STAGE: str = "film"
FILM_DUCK_SETTINGS: str = "threshold=0.02:ratio=6:attack=300:release=1500"
SRT_NAME: str = "film.srt"
SUBTITLE_LINGER_S: float = 0.3
SUBTITLE_GAP_S: float = 0.05
# libass sizes an SRT on a 288-unit-high canvas, so MarginV 54 is about 19% above the bottom
# edge (the bottom 15% stays clear) and MarginV 48 about 17%.
SUBTITLE_BASE_STYLE: str = (
    "FontName=Arial,PrimaryColour=&H00FFFFFF,OutlineColour=&H00000000,"
    "BorderStyle=1,Outline=0.7,Shadow=0.4,Alignment=2,MarginL=14,MarginR=14"
)
SUBTITLE_STYLE_9X16: str = f"{SUBTITLE_BASE_STYLE},FontSize=8,MarginV=54"
SUBTITLE_STYLE_16X9: str = f"{SUBTITLE_BASE_STYLE},FontSize=13,MarginV=48"
CARD_BACKGROUND: tuple[int, int, int] = (22, 17, 13)
CARD_TITLE_COLOUR: tuple[int, int, int] = (245, 222, 179)
CARD_TEXT_COLOUR: tuple[int, int, int] = (215, 205, 190)
CARD_FONT: Path = Path("C:/Windows/Fonts/arial.ttf")
CARD_MAX_TEXT_WIDTH: int = 960
FINAL_VIDEO_CODEC: tuple[str, ...] = ("-c:v", "libx264", "-preset", "medium", "-crf", "18", "-pix_fmt", "yuv420p")


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


# ---------------------------------------------------------------------------
# Film
# ---------------------------------------------------------------------------


def _srt_time(seconds: float) -> str:
    """Format seconds as an SRT timestamp."""
    millis = round(seconds * 1000)
    hours, millis = divmod(millis, 3_600_000)
    minutes, millis = divmod(millis, 60_000)
    secs, millis = divmod(millis, 1000)
    return f"{hours:02d}:{minutes:02d}:{secs:02d},{millis:03d}"


def build_srt(storyboard: dict[str, Any], timeline: list[ShotTiming], log_path: Path) -> str:
    """Build the English subtitles from subtitle_en, timed from the narration."""
    entries: list[str] = []
    for shot, timing in zip(storyboard["shots"], timeline):
        silences = None
        if len(shot.get("subtitle_en") or []) > 1 and len(timing.segments) == 1:
            silences = ffmpeg.detect_silences(
                timing.segments[0].wav, stage=FILM_STAGE, shot_id=timing.shot_id, log_path=log_path
            )
        cues = subtitle_cue_times(shot, timing, silences)
        for index, (begin, end, lines) in enumerate(cues):
            # Let each cue linger briefly, but never into the next cue or the next shot.
            if index + 1 < len(cues):
                limit = cues[index + 1][0] - SUBTITLE_GAP_S
            else:
                limit = timing.start_s + timing.length_s - SUBTITLE_GAP_S
            end = min(end + SUBTITLE_LINGER_S, limit)
            number = len(entries) + 1
            entries.append(f"{number}\n{_srt_time(begin)} --> {_srt_time(end)}\n" + "\n".join(lines))
            print(f"  {timing.shot_id} {begin:6.2f}-{end:6.2f}  {' / '.join(lines)}")
    return "\n\n".join(entries) + "\n"


def _card_font(size: int, text: str) -> ImageFont.FreeTypeFont:
    """Return a font for the end card, shrunk until the text fits the width."""
    while True:
        font = ImageFont.truetype(str(CARD_FONT), size) if CARD_FONT.is_file() else ImageFont.load_default(size)
        if font.getlength(text) <= CARD_MAX_TEXT_WIDTH or size <= 20:
            return font
        size -= 2


def draw_end_card(storyboard: dict[str, Any], used_wan: bool, path: Path) -> None:
    """Draw the AI end card from output.end_card (the Wan line only if a Wan clip was used)."""
    card = storyboard["output"]["end_card"]
    credits = list(card["credits"]) + ([card["wan_credit"]] if used_wan else [])
    image = Image.new("RGB", (shots.WIDTH, shots.HEIGHT), CARD_BACKGROUND)
    draw = ImageDraw.Draw(image)
    centre = shots.WIDTH / 2
    draw.text((centre, 700), card["title"], font=_card_font(96, card["title"]), fill=CARD_TITLE_COLOUR, anchor="mm")
    for index, line in enumerate(credits):
        draw.text((centre, 880 + index * 90), line, font=_card_font(40, line), fill=CARD_TEXT_COLOUR, anchor="mm")
    image.save(path, format="PNG")


def build_picture(
    clips: list[shots.Clip],
    timeline: list[ShotTiming],
    end_card: Path,
    fps: int,
    end_card_s: float,
    out_path: Path,
    log_path: Path,
) -> None:
    """Join the shots and end card with dissolves that start exactly at each timeline shot start."""
    args: list[str] = []
    for clip in clips:
        args += ["-i", str(clip.path)]
    args += ["-loop", "1", "-framerate", str(fps), "-t", f"{end_card_s:.6f}", "-i", str(end_card)]

    inputs = len(clips) + 1
    filters = [f"[{i}:v]fps={fps},settb=AVTB,setsar=1,format=yuv420p[v{i}]" for i in range(inputs)]
    # Each dissolve begins where the next shot starts; the last one leads into the end card.
    total_shots_s = sum(shot.length_s for shot in timeline)
    offsets = [shot.start_s for shot in timeline[1:]] + [total_shots_s]
    current = "[v0]"
    for index, offset in enumerate(offsets, start=1):
        label = f"[x{index}]"
        filters.append(
            f"{current}[v{index}]xfade=transition=fade:duration={shots.DISSOLVE_S}:offset={offset:.6f}{label}"
        )
        current = label

    frames = round((total_shots_s + end_card_s) * fps)
    args += ["-filter_complex", ";".join(filters), "-map", current, "-an"]
    args += [*shots.INTERMEDIATE_CODEC, "-r", str(fps), "-frames:v", str(frames), str(out_path)]
    ffmpeg.run_ffmpeg(
        args, stage=FILM_STAGE, step="join_shots", params={"offsets": offsets, "frames": frames}, log_path=log_path
    )


def build_mix(
    timeline: list[ShotTiming],
    music: Path,
    total_s: float,
    fade_s: float,
    out_path: Path,
    log_path: Path,
) -> None:
    """Place the narration on the timeline (as in the radio cut) and duck the score under it."""
    args: list[str] = []
    inputs = 0
    for shot in timeline:
        for segment in shot.segments:
            args += ["-i", str(segment.wav)]
            inputs += 1
    args += ["-i", str(music)]

    stereo = f"aformat=sample_fmts=fltp:sample_rates={AUDIO_RATE}:channel_layouts=stereo"
    # The score may be a few frames short of the film, so it fades out before whichever ends first.
    music_end = min(measure_duration_ffprobe(music), total_s)
    filters = _voice_filters(timeline, first_input=0)
    filters += [
        f"[voice]{stereo},apad,atrim=0:{total_s:.6f},asplit=2[voice_mix][voice_key]",
        f"[{inputs}:a]{stereo},volume={MUSIC_VOLUME},atrim=0:{music_end:.6f},"
        f"afade=t=out:st={music_end - fade_s:.6f}:d={fade_s:.6f},apad,atrim=0:{total_s:.6f}[bed]",
        f"[bed][voice_key]sidechaincompress={FILM_DUCK_SETTINGS}[ducked]",
        "[voice_mix][ducked]amix=inputs=2:duration=first:normalize=0[mix]",
    ]
    args += ["-filter_complex", ";".join(filters), "-map", "[mix]"]
    args += ["-c:a", "pcm_f32le", "-ar", str(AUDIO_RATE), "-t", f"{total_s:.6f}", str(out_path)]
    ffmpeg.run_ffmpeg(
        args,
        stage=FILM_STAGE,
        step="mix_audio",
        params={"music": music.name, "music_volume": MUSIC_VOLUME, "ducking": FILM_DUCK_SETTINGS},
        log_path=log_path,
    )


def normalise_loudness(source: Path, out_path: Path, log_path: Path) -> None:
    """Two-pass loudnorm to -14 LUFS with a -1 dBTP ceiling."""
    target = "loudnorm=I=-14:TP=-1"
    stderr = ffmpeg.run_ffmpeg(
        ["-i", str(source), "-af", f"{target}:LRA=11:print_format=json", "-f", "null", "-"],
        stage=FILM_STAGE,
        step="loudnorm_pass1",
        log_path=log_path,
    )
    measured = json.loads(stderr[stderr.rindex("{"): stderr.rindex("}") + 1])
    # Linear mode needs a target range at least as wide as the measured one.
    lra = min(max(float(measured["input_lra"]), 11.0), 50.0)
    second = (
        f"{target}:LRA={lra}:measured_I={measured['input_i']}:measured_TP={measured['input_tp']}"
        f":measured_LRA={measured['input_lra']}:measured_thresh={measured['input_thresh']}"
        f":offset={measured['target_offset']}:linear=true:print_format=summary,aresample={AUDIO_RATE}"
    )
    result = ffmpeg.run_ffmpeg(
        ["-i", str(source), "-af", second, "-c:a", "pcm_s24le", str(out_path)],
        stage=FILM_STAGE,
        step="loudnorm_pass2",
        params={"measured": measured},
        log_path=log_path,
    )
    mode = re.search(r"Normalization Type:\s*(\w+)", result)
    print(f"Loudness: measured {measured['input_i']} LUFS, normalised in {mode.group(1) if mode else '?'} mode")


def export_film(
    picture: Path,
    audio: Path,
    out_path: Path,
    landscape: bool,
    fps: int,
    total_s: float,
    log_path: Path,
) -> None:
    """Burn in the subtitles and write one H.264 + AAC file (run beside the SRT)."""
    style = SUBTITLE_STYLE_16X9 if landscape else SUBTITLE_STYLE_9X16
    subtitles = f"subtitles={SRT_NAME}:force_style='{style}'"
    if landscape:
        # The vertical picture centred over a blurred, enlarged copy of itself.
        video = (
            "[0:v]split=2[back][front];"
            "[back]scale=480:270:force_original_aspect_ratio=increase,crop=480:270,"
            "gblur=sigma=8,eq=brightness=-0.08,scale=1920:1080[bg];"
            "[front]scale=608:1080:flags=lanczos[fg];"
            f"[bg][fg]overlay=(W-w)/2:0,setsar=1,{subtitles},format=yuv420p[out]"
        )
    else:
        video = f"[0:v]{subtitles},format=yuv420p[out]"
    args = ["-i", str(picture), "-i", str(audio), "-filter_complex", video, "-map", "[out]", "-map", "1:a"]
    args += [*FINAL_VIDEO_CODEC, "-r", str(fps), "-fps_mode", "cfr"]
    args += ["-c:a", "aac", "-b:a", "192k", "-ar", str(AUDIO_RATE)]
    args += ["-t", f"{total_s:.6f}", "-movflags", "+faststart", str(out_path)]
    ffmpeg.run_ffmpeg(
        args,
        stage=FILM_STAGE,
        step="export_16x9" if landscape else "export_9x16",
        params={"output": out_path.name},
        log_path=log_path,
        cwd=out_path.parent,
    )


def report_output(path: Path, log_path: Path) -> None:
    """Print a finished file's duration, integrated loudness and true peak."""
    stderr = ffmpeg.run_ffmpeg(
        ["-i", str(path), "-vn", "-af", "ebur128=peak=true", "-f", "null", "-"],
        stage=FILM_STAGE,
        step="measure",
        params={"file": path.name},
        log_path=log_path,
    )
    summary = stderr[stderr.rindex("Summary:"):]
    loudness = float(re.search(r"I:\s*(-?[\d.]+) LUFS", summary).group(1))
    peak = float(re.search(r"Peak:\s*(-?[\d.]+) dBFS", summary).group(1))
    duration = measure_duration_ffprobe(path)
    print(f"[OK] {path}: {duration:.2f}s, {loudness:.1f} LUFS, true peak {peak:.1f} dBTP")
    if peak > -1.0:
        print(f"[WARN] {path.name}: true peak is above -1 dBTP")
    if not MIN_TOTAL_S <= duration <= MAX_TOTAL_S:
        print(f"[WARN] {path.name}: duration is outside {MIN_TOTAL_S:.0f}-{MAX_TOTAL_S:.0f}s")


def run_film(
    storyboard_path: Path = config.STORYBOARD_PATH,
    log_path: Path = config.RUNS_LOG_PATH,
) -> list[Path]:
    """Render outputs/final/film_9x16.mp4 and film_16x9.mp4 and return their paths."""
    storyboard = json.loads(storyboard_path.read_text(encoding="utf-8"))
    timeline = build_timeline(storyboard, config.stage_output_dir("narration", create=False))
    music = chosen_track(storyboard)
    if music is None:
        raise ValueError("music.chosen is not set. Run --stage music-import --choose <seed> first.")
    fps = int(storyboard["output"]["fps"])
    end_card_s = float(storyboard["output"]["end_card_s"])
    total_s = sum(shot.length_s for shot in timeline) + end_card_s

    clips = shots.render_shots(storyboard, timeline, log_path)
    final_dir = config.stage_output_dir("final")
    work = final_dir / "work"
    work.mkdir(parents=True, exist_ok=True)

    print("Subtitles:")
    (final_dir / SRT_NAME).write_text(build_srt(storyboard, timeline, log_path), encoding="utf-8")
    card = work / "end_card.png"
    draw_end_card(storyboard, any(clip.used_wan for clip in clips), card)

    picture = work / "picture.mp4"
    build_picture(clips, timeline, card, fps, end_card_s, picture, log_path)
    mix, normalised = work / "mix.wav", work / "mix_loudnorm.wav"
    build_mix(timeline, music, total_s, end_card_s, mix, log_path)
    normalise_loudness(mix, normalised, log_path)

    outputs = [final_dir / "film_9x16.mp4", final_dir / "film_16x9.mp4"]
    for out_path, landscape in zip(outputs, (False, True)):
        export_film(picture, normalised, out_path, landscape, fps, total_s, log_path)
    for out_path in outputs:
        report_output(out_path, log_path)
    return outputs
