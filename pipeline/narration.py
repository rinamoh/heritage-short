"""Narration synthesis stage supporting Gemini TTS and Addis AI TTS with caching.

One WAV per narration segment. Also hosts the E2 (voices) and E3 (clipped ending) helpers.
"""

import argparse
import array
import base64
from collections.abc import Callable, Sequence
from dataclasses import dataclass, replace
import io
import json
import math
from pathlib import Path
import subprocess
import sys
import time
from typing import Any
import wave

import addisai
from google import genai

from pipeline.common import cache, config, log, retry

DEFAULT_GEMINI_TTS_MODEL: str = "gemini-3.8-flash-tts"
DEFAULT_GEMINI_VOICE: str = "Kore"
DEFAULT_GEMINI_STYLE: str = "warm, calm, restrained narration"
DEFAULT_ADDIS_MODEL: str = "addisai-voice"
DEFAULT_ADDIS_VOICE: str = "am-hamen"
ADDIS_OUTPUT_FORMAT: str = "wav_44100"
ADDIS_MP3_FORMAT: str = "mp3_44100"
GEMINI_TTS_COOLDOWN_S: float = 21.0
DEFAULT_GEMINI_E2_MODEL: str = "gemini-3.8-flash-lite-tts"
DEFAULT_MAX_GEMINI_CALLS: int = 9
# attempts=1 stops the SDK's own retries, which would silently re-send 429s and spend quota.
GEMINI_HTTP_OPTIONS: dict[str, Any] = {"api_version": "v1beta", "retry_options": {"attempts": 1}}

END_WINDOW_S: float = 0.03
CLIPPED_END_THRESHOLD_DB: float = -45.0
GAP_BLOCK_S: float = 0.01
MIN_GAP_S: float = 0.15

PROBE_ELLIPSIS: str = "…"
PROBE_EXTRA_WORD: str = "እሺ።"


class QuotaGuardError(RuntimeError):
    """Raised before any call when a run would make too many Gemini TTS calls."""


@dataclass(frozen=True)
class VoiceConfig:
    """Resolved TTS provider configuration for a single shot."""

    provider: str
    model: str
    voice_name: str
    style: str | None
    settings: dict[str, Any]
    language: str


def _ensure_wav_bytes(audio_bytes: bytes, sample_rate: int = 24000) -> bytes:
    """Wrap raw 16-bit mono PCM bytes in a WAV header if a RIFF header is absent."""
    if audio_bytes[:4] == b"RIFF":
        return audio_bytes
    buffer = io.BytesIO()
    with wave.open(buffer, "wb") as wav_file:
        wav_file.setnchannels(1)
        wav_file.setsampwidth(2)
        wav_file.setframerate(sample_rate)
        wav_file.writeframes(audio_bytes)
    return buffer.getvalue()


def _extract_interaction_audio(interaction: Any) -> bytes:
    """Extract raw or base64-decoded audio bytes from a Gemini interaction response."""
    output_audio = getattr(interaction, "output_audio", None)
    if output_audio is not None and getattr(output_audio, "data", None):
        data = output_audio.data
        return data if isinstance(data, bytes) else base64.b64decode(data)

    outputs = getattr(interaction, "outputs", None) or []
    for item in outputs:
        if getattr(item, "type", None) == "audio" and getattr(item, "data", None):
            data = item.data
            return data if isinstance(data, bytes) else base64.b64decode(data)

    raise ValueError("Gemini interaction response contained no audio payload.")


def resolve_voice_config(
    storyboard: dict[str, Any],
    shot: dict[str, Any],
    provider_override: str | None = None,
) -> VoiceConfig:
    """Resolve provider, model, voice, style, and settings for a shot."""
    voice = storyboard.get("voice") or {}
    narration = shot.get("narration") or {}
    storyboard_provider = str(voice.get("provider") or "addis")
    provider = provider_override or storyboard_provider
    language = str(storyboard.get("language") or "am")
    raw_name = str(voice.get("name") or "")
    # A storyboard model belongs to its own provider; never send it to another one.
    raw_model = voice.get("model") if provider == storyboard_provider else None

    if provider == "gemini":
        model = str(raw_model) if raw_model else DEFAULT_GEMINI_TTS_MODEL
        if provider_override and storyboard_provider != "gemini" and raw_name.startswith(f"{language}-"):
            voice_name = DEFAULT_GEMINI_VOICE
        else:
            voice_name = raw_name or DEFAULT_GEMINI_VOICE
        style = narration.get("style_override") or voice.get("style") or DEFAULT_GEMINI_STYLE
        return VoiceConfig(
            provider="gemini",
            model=model,
            voice_name=voice_name,
            style=str(style),
            settings={},
            language=language,
        )

    if provider == "addis":
        model = str(raw_model) if raw_model else DEFAULT_ADDIS_MODEL
        if provider_override and storyboard_provider != "addis" and "-" not in raw_name:
            voice_name = DEFAULT_ADDIS_VOICE
        else:
            voice_name = raw_name or DEFAULT_ADDIS_VOICE
        settings = dict(voice.get("settings") or {})
        return VoiceConfig(
            provider="addis",
            model=model,
            voice_name=voice_name,
            style=None,
            settings=settings,
            language=language,
        )

    raise ValueError(f"Unsupported narration provider: {provider!r}")


_last_gemini_call_at: float | None = None


def _wait_for_gemini_slot() -> None:
    """Keep every Gemini TTS request, retries included, at least 21 s apart."""
    global _last_gemini_call_at
    if _last_gemini_call_at is not None:
        wait = GEMINI_TTS_COOLDOWN_S - (time.monotonic() - _last_gemini_call_at)
        if wait > 0:
            print(f"Waiting {wait:.0f}s for the Gemini TTS rate limit...")
            time.sleep(wait)
    _last_gemini_call_at = time.monotonic()


def is_quota_error(result: retry.CallResult) -> bool:
    """Return True when a failed call hit the 429 quota limit."""
    message = (result.error or "").lower()
    return result.status_code == 429 or "resource_exhausted" in message or "quota" in message


def guard_gemini_calls(planned: int, allow_calls: int | None) -> None:
    """Print the planned Gemini TTS calls and abort if they exceed the limit."""
    limit = DEFAULT_MAX_GEMINI_CALLS if allow_calls is None else allow_calls
    print(f"Planned Gemini TTS calls: {planned} (limit {limit})")
    if planned > limit:
        raise QuotaGuardError(
            f"{planned} Gemini TTS calls planned, over the limit of {limit}. "
            f"No calls were made. Pass --allow-calls {planned} to run anyway."
        )


def _synthesize_gemini(
    text: str,
    cfg: VoiceConfig,
    out_path: Path,
    api_key: str,
) -> dict[str, Any]:
    """Synthesize speech with Gemini TTS (v1beta interactions API) and save WAV."""
    if not api_key:
        raise ValueError("Missing GEMINI_API_KEY in .env")
    client = genai.Client(api_key=api_key, http_options=GEMINI_HTTP_OPTIONS)
    content_item: dict[str, Any] = {"type": "text", "text": text}
    if cfg.style:
        content_item["annotations"] = [{"type": "speech_metadata", "style": cfg.style}]
    _wait_for_gemini_slot()
    interaction = client.interactions.create(
        model=cfg.model,
        input=[{"type": "user_input", "content": [content_item]}],
        response_format={"type": "audio"},
        generation_config={"speech_config": [{"voice": cfg.voice_name}]},
    )
    errors = getattr(interaction, "errors", None)
    if errors:
        raise RuntimeError(f"Gemini interaction errors: {errors}")

    wav_bytes = _ensure_wav_bytes(_extract_interaction_audio(interaction))
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_bytes(wav_bytes)
    return {}


def _synthesize_addis(
    text: str,
    cfg: VoiceConfig,
    out_path: Path,
    api_key: str,
    output_format: str = ADDIS_OUTPUT_FORMAT,
) -> dict[str, Any]:
    """Synthesize Amharic speech with Addis AI SDK, save the audio, and return usage metadata."""
    if not api_key:
        raise ValueError("Missing ADDIS_API_KEY in .env")
    client = addisai.AddisAI(api_key=api_key)
    voice_settings = cfg.settings if cfg.settings else None
    clip = client.voice.generate(
        voice_id=cfg.voice_name,
        text=text,
        language=cfg.language,
        output_format=output_format,
        voice_settings=voice_settings,
    )
    out_path.parent.mkdir(parents=True, exist_ok=True)
    clip.to_file(str(out_path))
    usage = clip.usage or {}
    return {
        "credits_used": usage.get("credits_used"),
        "currency": usage.get("currency"),
        "duration_seconds": clip.duration_seconds,
    }


def synthesize_narration(
    text: str,
    cfg: VoiceConfig,
    out_path: Path,
    settings: config.Settings,
) -> dict[str, Any]:
    """Dispatch narration synthesis to the configured TTS provider and save WAV."""
    if cfg.provider == "gemini":
        return _synthesize_gemini(text=text, cfg=cfg, out_path=out_path, api_key=settings.gemini_api_key)
    if cfg.provider == "addis":
        return _synthesize_addis(text=text, cfg=cfg, out_path=out_path, api_key=settings.addis_api_key)
    raise ValueError(f"Unsupported narration provider: {cfg.provider!r}")


def measure_duration_ffprobe(wav_path: Path) -> float:
    """Measure the audio duration in seconds of a WAV file using ffprobe."""
    cmd = [
        "ffprobe",
        "-v",
        "error",
        "-show_entries",
        "format=duration",
        "-of",
        "default=noprint_wrappers=1:nokey=1",
        str(wav_path),
    ]
    proc = subprocess.run(cmd, capture_output=True, text=True, check=True)
    return float(proc.stdout.strip())


def _read_pcm16(wav_path: Path) -> tuple[array.array, wave._wave_params]:
    """Read a 16-bit WAV into an array of samples plus its header parameters."""
    with wave.open(str(wav_path), "rb") as handle:
        params = handle.getparams()
        if params.sampwidth != 2:
            raise ValueError(f"Expected 16-bit PCM in {wav_path.name}, got {params.sampwidth * 8}-bit")
        return array.array("h", handle.readframes(params.nframes)), params


def _level_db(samples: array.array) -> float:
    """Return the RMS level of 16-bit samples in dBFS."""
    if not samples:
        return -120.0
    rms = math.sqrt(sum(s * s for s in samples) / len(samples))
    return 20 * math.log10(max(rms, 0.03) / 32768)


def measure_end_level_db(wav_path: Path) -> float:
    """Return the level of the last 30 ms of a WAV in dBFS."""
    samples, params = _read_pcm16(wav_path)
    count = int(params.framerate * END_WINDOW_S) * params.nchannels
    return _level_db(samples[-count:])


def check_clipped_end(wav_path: Path) -> dict[str, Any]:
    """Report whether a WAV is still audible in its last 30 ms (a sign it was cut off)."""
    level = measure_end_level_db(wav_path)
    return {"end_level_db": round(level, 1), "clipped_end": level > CLIPPED_END_THRESHOLD_DB}


def build_segment_key(text: str, cfg: VoiceConfig) -> tuple[str, dict[str, Any]]:
    """Build the cache key and loggable parameter dict for one narration segment."""
    params: dict[str, Any] = {
        "provider": cfg.provider,
        "voice": cfg.voice_name,
        "style": cfg.style,
        "settings": cfg.settings,
        "language": cfg.language,
    }
    if cfg.provider == "addis":
        params["output_format"] = ADDIS_OUTPUT_FORMAT
    key = cache.build_cache_key(model=cfg.model, prompt=text, params=params)
    return key, params


def segment_texts(shot: dict[str, Any]) -> list[str]:
    """Return the stripped text of every narration segment in a shot (empty for silent shots)."""
    segments = (shot.get("narration") or {}).get("segments") or []
    return [str(segment["text_am"]).strip() for segment in segments]


def parse_shots_arg(raw_shots: str | None) -> set[str] | None:
    """Parse a comma-separated --shots argument into a set of shot IDs, or None."""
    if not raw_shots:
        return None
    items = {part.strip() for part in raw_shots.split(",") if part.strip()}
    return items or None


def _load_storyboard(storyboard_path: Path) -> dict[str, Any]:
    """Read storyboard.json."""
    with storyboard_path.open("r", encoding="utf-8") as handle:
        return json.load(handle)


def _find_shot(storyboard: dict[str, Any], shot_id: str) -> dict[str, Any]:
    """Return one narrated shot by id, or raise a clear error."""
    for shot in storyboard.get("shots") or []:
        if shot.get("id") == shot_id:
            if not segment_texts(shot):
                raise ValueError(f"Shot {shot_id} is silent; it has no narration to render.")
            return shot
    raise ValueError(f"Unknown shot id: {shot_id}")


def _call_and_log(
    stage: str,
    shot_id: str,
    cfg: VoiceConfig,
    params: dict[str, Any],
    synthesize: Callable[[], dict[str, Any]],
    check_path: Path,
    sleep_fn: Callable[[float], None],
    log_path: Path,
) -> retry.CallResult:
    """Run one TTS call with retries, check the saved file's ending, and log the call."""
    started = time.monotonic()
    result = retry.run_with_retry(synthesize, sleep_fn=sleep_fn)
    latency = time.monotonic() - started

    full_params = dict(params)
    if result.ok:
        usage = result.value if isinstance(result.value, dict) else {}
        full_params.update({k: v for k, v in usage.items() if v is not None})
        if check_path.suffix == ".wav" and check_path.is_file():
            full_params.update(check_clipped_end(check_path))
    log.log_call(
        stage=stage,
        shot_id=shot_id,
        provider=cfg.provider,
        model=cfg.model,
        params=full_params,
        latency_s=latency,
        cache_hit=False,
        status="ok" if result.ok else "error",
        error=result.error,
        log_path=log_path,
    )
    if not result.ok:
        print(f"[FAIL] {shot_id} ({cfg.provider}, {cfg.voice_name}): {result.error}")
    return result


def _describe(wav_path: Path) -> str:
    """Format a WAV's name, length, and ending check for console output."""
    ending = check_clipped_end(wav_path)
    flag = "  CLIPPED END" if ending["clipped_end"] else ""
    return (
        f"{wav_path.name} ({measure_duration_ffprobe(wav_path):.2f}s, "
        f"end {ending['end_level_db']} dBFS){flag}"
    )


def _plan_misses(
    storyboard: dict[str, Any],
    shots: Sequence[dict[str, Any]],
    narration_dir: Path,
    provider_override: str | None,
) -> int:
    """Count the Gemini TTS calls a run would make (cache misses only)."""
    misses: set[Path] = set()
    for shot in shots:
        cfg = resolve_voice_config(storyboard, shot, provider_override=provider_override)
        if cfg.provider != "gemini":
            continue
        for text in segment_texts(shot):
            path = cache.cache_path(narration_dir, str(shot["id"]), build_segment_key(text, cfg)[0], "wav")
            if cache.get_cached(path) is None:
                misses.add(path)
    return len(misses)


def run_narration(
    shot_ids: set[str] | None = None,
    provider_override: str | None = None,
    storyboard_path: Path = config.STORYBOARD_PATH,
    output_dir: Path | None = None,
    log_path: Path = config.RUNS_LOG_PATH,
    sleep_fn: Any = time.sleep,
    allow_calls: int | None = None,
) -> list[str]:
    """Render one WAV per segment, write durations.json, and return the segments still missing."""
    storyboard = _load_storyboard(storyboard_path)
    shots = storyboard.get("shots") or []
    if shot_ids:
        unknown = sorted(shot_ids - {s.get("id") for s in shots})
        if unknown:
            raise ValueError(f"Unknown shot id(s): {', '.join(unknown)}")
    selected = [s for s in shots if shot_ids is None or s["id"] in shot_ids]

    narration_dir = output_dir if output_dir is not None else config.stage_output_dir("narration")
    narration_dir.mkdir(parents=True, exist_ok=True)
    durations_path = narration_dir / "durations.json"
    settings = config.load_settings()

    provider = provider_override or str((storyboard.get("voice") or {}).get("provider") or "addis")
    if provider == "gemini":
        guard_gemini_calls(_plan_misses(storyboard, selected, narration_dir, provider_override), allow_calls)

    # A --shots run keeps the entries of the shots it does not touch.
    entries: dict[str, Any] = {}
    if shot_ids and durations_path.is_file():
        entries = json.loads(durations_path.read_text(encoding="utf-8")).get("shots") or {}

    missing: list[str] = []
    quota_hit = False
    for shot in selected:
        shot_id = str(shot["id"])
        entries.pop(shot_id, None)
        texts = segment_texts(shot)
        if not texts:
            continue

        cfg = resolve_voice_config(storyboard, shot, provider_override=provider_override)
        segments: list[dict[str, Any]] = []
        for number, text in enumerate(texts, start=1):
            key, params = build_segment_key(text, cfg)
            out_path = cache.cache_path(narration_dir, shot_id, key, "wav")
            log_params = {**params, "segment": number}
            cache_hit = cache.get_cached(out_path) is not None

            if cache_hit:
                log.log_call(
                    stage="narration",
                    shot_id=shot_id,
                    provider=cfg.provider,
                    model=cfg.model,
                    params={**log_params, **check_clipped_end(out_path)},
                    cache_hit=True,
                    status="ok",
                    log_path=log_path,
                )
            elif quota_hit:
                missing.append(f"{shot_id}.{number}")
                continue
            else:
                result = _call_and_log(
                    "narration",
                    shot_id,
                    cfg,
                    log_params,
                    lambda t=text, c=cfg, p=out_path: synthesize_narration(t, c, p, settings),
                    out_path,
                    sleep_fn,
                    log_path,
                )
                if not result.ok:
                    missing.append(f"{shot_id}.{number}")
                    if is_quota_error(result):
                        quota_hit = True
                        print("[STOP] Quota reached (429). No more calls will be made.")
                    continue

            segments.append(
                {
                    "file": out_path.name,
                    "duration_s": round(measure_duration_ffprobe(out_path), 3),
                    "clipped_end": check_clipped_end(out_path)["clipped_end"],
                    "provider": cfg.provider,
                    "cache_hit": cache_hit,
                }
            )
            print(f"[{'CACHE' if cache_hit else 'OK'}] {shot_id}.{number} -> {_describe(out_path)}")

        # A shot with a missing segment is left out, so the radio stage reports it.
        if len(segments) == len(texts):
            entries[shot_id] = {"segments": segments}

    total = sum(seg["duration_s"] for entry in entries.values() for seg in entry.get("segments", []))
    summary = {
        "provider": provider,
        "total_duration_s": round(total, 3),
        "shots": dict(sorted(entries.items())),
    }
    durations_path.write_text(json.dumps(summary, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(f"Wrote {durations_path} (total speech: {summary['total_duration_s']:.2f}s).")
    if missing:
        print(f"Still missing: {', '.join(missing)}. Re-run to generate only these.")
    return missing


def list_voices(log_path: Path = config.RUNS_LOG_PATH) -> None:
    """Print the Amharic voices Addis AI offers."""
    settings = config.load_settings()
    if not settings.addis_api_key:
        raise ValueError("Missing ADDIS_API_KEY in .env")
    client = addisai.AddisAI(api_key=settings.addis_api_key)
    started = time.monotonic()
    result = retry.run_with_retry(lambda: client.voices.list(language="am"))
    log.log_call(
        stage="narration_voices",
        shot_id=None,
        provider="addis",
        model=DEFAULT_ADDIS_MODEL,
        params={"language": "am"},
        latency_s=time.monotonic() - started,
        status="ok" if result.ok else "error",
        error=result.error,
        log_path=log_path,
    )
    if not result.ok:
        print(f"[FAIL] voices.list: {result.error}")
        return
    for voice in result.value:
        print(json.dumps(voice, ensure_ascii=False))
    print(f"{len(result.value)} Amharic voice(s).")


def run_voice_test(
    shot_id: str,
    voices: Sequence[str],
    speed: float | None = None,
    model: str | None = None,
    provider_override: str | None = None,
    allow_calls: int | None = None,
    log_path: Path = config.RUNS_LOG_PATH,
) -> None:
    """E2: render one shot in several voices into outputs/narration/e2/.

    Gemini uses the Lite TTS model unless --model says otherwise, so the film's quota is untouched.
    """
    storyboard = _load_storyboard(config.STORYBOARD_PATH)
    shot = _find_shot(storyboard, shot_id)
    base = resolve_voice_config(storyboard, shot, provider_override=provider_override)
    if base.provider == "gemini":
        base = replace(base, model=model or DEFAULT_GEMINI_E2_MODEL)
    elif model:
        base = replace(base, model=model)
    out_dir = config.stage_output_dir("narration") / "e2"
    settings = config.load_settings()

    jobs: list[tuple[VoiceConfig, int, str, dict[str, Any], Path]] = []
    for voice in voices:
        voice_settings = dict(base.settings)
        if speed is not None and base.provider == "addis":
            voice_settings["speed"] = speed
        cfg = replace(base, voice_name=voice, settings=voice_settings)
        for number, text in enumerate(segment_texts(shot), start=1):
            key, params = build_segment_key(text, cfg)
            path = cache.cache_path(out_dir, f"{shot_id}_{voice}", key, "wav")
            jobs.append((cfg, number, text, params, path))

    if base.provider == "gemini":
        print(f"Model: {base.model}")
        guard_gemini_calls(sum(cache.get_cached(job[4]) is None for job in jobs), allow_calls)

    for cfg, number, text, params, out_path in jobs:
        if cache.get_cached(out_path) is None:
            result = _call_and_log(
                "narration_e2",
                shot_id,
                cfg,
                {**params, "segment": number},
                lambda t=text, c=cfg, p=out_path: synthesize_narration(t, c, p, settings),
                out_path,
                time.sleep,
                log_path,
            )
            if not result.ok:
                if is_quota_error(result):
                    print("[STOP] Quota reached (429). Re-run later for the remaining voices.")
                    break
                continue
        print(f"{cfg.voice_name}: {_describe(out_path)}")
    print(f"Files are in {out_dir}")


def find_cut_before_last_word(wav_path: Path) -> float | None:
    """Return the middle of the last silent gap that still has sound after it, in seconds."""
    samples, params = _read_pcm16(wav_path)
    block = int(params.framerate * GAP_BLOCK_S) * params.nchannels
    loud = [
        _level_db(samples[i:i + block]) > CLIPPED_END_THRESHOLD_DB
        for i in range(0, len(samples), block)
    ]
    min_blocks = round(MIN_GAP_S / GAP_BLOCK_S)
    gap_end: int | None = None
    # Walk backwards to the first long enough quiet run that follows some sound.
    for index in range(len(loud) - 2, -1, -1):
        if not loud[index] and loud[index + 1]:
            gap_end = index + 1
        elif loud[index] and gap_end is not None:
            gap_start = index + 1
            if gap_end - gap_start >= min_blocks:
                return (gap_start + gap_end) / 2 * GAP_BLOCK_S
            gap_end = None
    return None


def trim_wav(source: Path, target: Path, end_s: float) -> None:
    """Write the first end_s seconds of a WAV to a new file."""
    with wave.open(str(source), "rb") as reader:
        params = reader.getparams()
        frames = reader.readframes(int(end_s * params.framerate))
    with wave.open(str(target), "wb") as writer:
        writer.setparams(params)
        writer.writeframes(frames)


def _convert_to_wav(source: Path, target: Path) -> None:
    """Decode an audio file to 16-bit PCM WAV with FFmpeg."""
    cmd = ["ffmpeg", "-y", "-v", "error", "-i", str(source), "-c:a", "pcm_s16le", str(target)]
    subprocess.run(cmd, check=True)


def run_probe(
    shot_id: str,
    extra_word: str = PROBE_EXTRA_WORD,
    log_path: Path = config.RUNS_LOG_PATH,
) -> None:
    """E3: render a shot's text four ways into outputs/narration/e3/ to study clipped endings."""
    storyboard = _load_storyboard(config.STORYBOARD_PATH)
    shot = _find_shot(storyboard, shot_id)
    cfg = resolve_voice_config(storyboard, shot, provider_override="addis")
    # The last segment is the one whose ending is being studied.
    text = segment_texts(shot)[-1]
    out_dir = config.stage_output_dir("narration") / "e3"
    settings = config.load_settings()

    variants: tuple[tuple[str, str, str], ...] = (
        ("A", text, ADDIS_OUTPUT_FORMAT),
        ("B", text, ADDIS_MP3_FORMAT),
        ("C", text + PROBE_ELLIPSIS, ADDIS_OUTPUT_FORMAT),
        ("D", f"{text} {extra_word}", ADDIS_OUTPUT_FORMAT),
    )
    for name, variant_text, output_format in variants:
        params = {**build_segment_key(variant_text, cfg)[1], "output_format": output_format}
        key = cache.build_cache_key(model=cfg.model, prompt=variant_text, params=params)
        extension = "mp3" if output_format == ADDIS_MP3_FORMAT else "wav"
        raw_path = cache.cache_path(out_dir, f"{shot_id}_{name}", key, extension)
        log_params = {**params, "variant": name, "text": variant_text}

        if cache.get_cached(raw_path) is None:
            result = _call_and_log(
                "narration_e3",
                shot_id,
                cfg,
                log_params,
                lambda t=variant_text, p=raw_path, f=output_format: _synthesize_addis(
                    t, cfg, p, settings.addis_api_key, output_format=f
                ),
                raw_path,
                time.sleep,
                log_path,
            )
            if not result.ok:
                continue

        if name == "B":
            wav_path = raw_path.with_suffix(".wav")
            _convert_to_wav(raw_path, wav_path)
            _log_derived(shot_id, cfg, log_params, "mp3_to_wav", wav_path, log_path)
        elif name == "D":
            cut_s = find_cut_before_last_word(raw_path)
            if cut_s is None:
                print(f"D: no silent gap before the extra word; left untrimmed: {_describe(raw_path)}")
                continue
            wav_path = raw_path.with_name(f"{raw_path.stem}_trimmed.wav")
            trim_wav(raw_path, wav_path, cut_s)
            _log_derived(shot_id, cfg, {**log_params, "cut_s": round(cut_s, 3)}, "trim", wav_path, log_path)
        else:
            wav_path = raw_path
        print(f"{name}: {_describe(wav_path)}")
    print(f"Files are in {out_dir}")


def _log_derived(
    shot_id: str,
    cfg: VoiceConfig,
    params: dict[str, Any],
    step: str,
    wav_path: Path,
    log_path: Path,
) -> None:
    """Log the ending check of a probe file produced locally from a TTS result."""
    log.log_call(
        stage="narration_e3",
        shot_id=shot_id,
        provider="local",
        model=step,
        params={**params, "voice_model": cfg.model, "file": wav_path.name, **check_clipped_end(wav_path)},
        status="ok",
        log_path=log_path,
    )


def build_parser() -> argparse.ArgumentParser:
    """Build the command-line argument parser for the narration stage."""
    parser = argparse.ArgumentParser(
        description="Generate Amharic narration WAVs and measure durations.",
        allow_abbrev=False,
    )
    parser.add_argument(
        "--shots",
        default=None,
        help="Comma-separated list of shot IDs to render (e.g. s03,s10).",
    )
    parser.add_argument(
        "--provider",
        choices=("gemini", "addis"),
        default=None,
        help="Override storyboard voice.provider for this run.",
    )
    parser.add_argument("--list-voices", action="store_true", help="Print Addis AI Amharic voices.")
    parser.add_argument("--shot", default=None, help="E2: the shot to render with --voices.")
    parser.add_argument("--voices", default=None, help="E2: comma-separated voice names or ids.")
    parser.add_argument("--model", default=None, help="E2: TTS model (Gemini default: Flash Lite TTS).")
    parser.add_argument("--speed", type=float, default=None, help="E2: Addis AI speed setting.")
    parser.add_argument(
        "--allow-calls",
        type=int,
        default=None,
        help=f"Allow this many Gemini TTS calls (default limit {DEFAULT_MAX_GEMINI_CALLS}).",
    )
    parser.add_argument("--probe", default=None, help="E3: shot id to render in variants A-D.")
    parser.add_argument("--probe-word", default=PROBE_EXTRA_WORD, help="E3: extra word for variant D.")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    """Parse narration CLI flags and run the requested action."""
    sys.stdout.reconfigure(errors="replace")
    parser = build_parser()
    args = parser.parse_args(list(argv) if argv is not None else None)

    try:
        if args.list_voices:
            list_voices()
        elif args.probe:
            run_probe(args.probe, extra_word=args.probe_word)
        elif args.shot or args.voices:
            voices = [v.strip() for v in (args.voices or "").split(",") if v.strip()]
            if not args.shot or not voices:
                parser.error("--shot and --voices must be used together")
            run_voice_test(
                args.shot,
                voices,
                speed=args.speed,
                model=args.model,
                provider_override=args.provider,
                allow_calls=args.allow_calls,
            )
        else:
            missing = run_narration(
                shot_ids=parse_shots_arg(args.shots),
                provider_override=args.provider,
                allow_calls=args.allow_calls,
            )
            return 1 if missing else 0
    except QuotaGuardError as exc:
        print(f"[ABORT] {exc}")
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
