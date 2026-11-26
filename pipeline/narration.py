"""Narration synthesis stage supporting Gemini TTS and Addis AI TTS with caching."""

import argparse
import base64
from collections.abc import Sequence
from dataclasses import dataclass
import io
import json
from pathlib import Path
import subprocess
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
GEMINI_TTS_COOLDOWN_S: float = 21.0


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
    raw_model = voice.get("model")

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


def _synthesize_gemini(
    text: str,
    cfg: VoiceConfig,
    out_path: Path,
    api_key: str,
) -> dict[str, Any]:
    """Synthesize speech with Gemini TTS (v1beta interactions API) and save WAV."""
    if not api_key:
        raise ValueError("Missing GEMINI_API_KEY in .env")
    client = genai.Client(api_key=api_key, http_options={"api_version": "v1beta"})
    content_item: dict[str, Any] = {"type": "text", "text": text}
    if cfg.style:
        content_item["annotations"] = [{"type": "speech_metadata", "style": cfg.style}]
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
) -> dict[str, Any]:
    """Synthesize Amharic speech with Addis AI SDK, save WAV, and return usage metadata."""
    if not api_key:
        raise ValueError("Missing ADDIS_API_KEY in .env")
    client = addisai.AddisAI(api_key=api_key)
    voice_settings = cfg.settings if cfg.settings else None
    clip = client.voice.generate(
        voice_id=cfg.voice_name,
        text=text,
        language=cfg.language,
        output_format=ADDIS_OUTPUT_FORMAT,
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


def _build_shot_cache_key(text: str, cfg: VoiceConfig) -> tuple[str, dict[str, Any]]:
    """Build the cache key and loggable parameter dict for one narration line."""
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


def parse_shots_arg(raw_shots: str | None) -> set[str] | None:
    """Parse a comma-separated --shots argument into a set of shot IDs, or None."""
    if not raw_shots:
        return None
    items = {part.strip() for part in raw_shots.split(",") if part.strip()}
    return items or None


def run_narration(
    shot_ids: set[str] | None = None,
    provider_override: str | None = None,
    storyboard_path: Path = config.STORYBOARD_PATH,
    output_dir: Path | None = None,
    log_path: Path = config.RUNS_LOG_PATH,
    sleep_fn: Any = time.sleep,
) -> Path:
    """Render narration WAVs for non-empty shots, measure durations, and write durations.json."""
    with storyboard_path.open("r", encoding="utf-8") as handle:
        storyboard = json.load(handle)

    shots = storyboard.get("shots") or []
    all_ids = {s.get("id") for s in shots if isinstance(s, dict)}
    if shot_ids:
        unknown = sorted(shot_ids - all_ids)
        if unknown:
            raise ValueError(f"Unknown shot id(s): {', '.join(unknown)}")

    narration_dir = output_dir if output_dir is not None else config.stage_output_dir("narration")
    narration_dir.mkdir(parents=True, exist_ok=True)
    settings = config.load_settings()

    durations: dict[str, dict[str, Any]] = {}
    last_gemini_call_at: float | None = None
    active_provider = provider_override or str((storyboard.get("voice") or {}).get("provider") or "addis")

    for shot in shots:
        shot_id = str(shot["id"])
        if shot_ids is not None and shot_id not in shot_ids:
            continue

        text = str((shot.get("narration") or {}).get("text_am") or "").strip()
        if not text:
            continue

        cfg = resolve_voice_config(storyboard, shot, provider_override=provider_override)
        key, log_params = _build_shot_cache_key(text, cfg)
        out_path = cache.cache_path(narration_dir, shot_id, key, "wav")

        cached_file = cache.get_cached(out_path)
        if cached_file is not None:
            log.log_call(
                stage="narration",
                shot_id=shot_id,
                provider=cfg.provider,
                model=cfg.model,
                params=log_params,
                latency_s=0.0,
                cache_hit=True,
                status="ok",
                log_path=log_path,
            )
            dur = measure_duration_ffprobe(cached_file)
            durations[shot_id] = {
                "file": cached_file.name,
                "duration_s": round(dur, 3),
                "storyboard_duration_s": shot.get("duration_s"),
                "provider": cfg.provider,
                "cache_hit": True,
            }
            print(f"[CACHE] {shot_id} -> {cached_file.name} ({dur:.2f}s)")
            continue

        if cfg.provider == "gemini" and last_gemini_call_at is not None:
            elapsed = time.monotonic() - last_gemini_call_at
            if elapsed < GEMINI_TTS_COOLDOWN_S:
                sleep_fn(GEMINI_TTS_COOLDOWN_S - elapsed)

        started = time.monotonic()
        result = retry.run_with_retry(
            lambda t=text, c=cfg, p=out_path: synthesize_narration(t, c, p, settings),
            sleep_fn=sleep_fn,
        )
        latency = time.monotonic() - started
        if cfg.provider == "gemini":
            last_gemini_call_at = time.monotonic()

        if not result.ok:
            log.log_call(
                stage="narration",
                shot_id=shot_id,
                provider=cfg.provider,
                model=cfg.model,
                params=log_params,
                latency_s=latency,
                cache_hit=False,
                status="error",
                error=result.error,
                log_path=log_path,
            )
            print(f"[FAIL] {shot_id} ({cfg.provider}): {result.error}")
            continue

        usage_meta = result.value if isinstance(result.value, dict) else {}
        full_params = {**log_params, **{k: v for k, v in usage_meta.items() if v is not None}}
        log.log_call(
            stage="narration",
            shot_id=shot_id,
            provider=cfg.provider,
            model=cfg.model,
            params=full_params,
            latency_s=latency,
            cache_hit=False,
            status="ok",
            log_path=log_path,
        )
        dur = measure_duration_ffprobe(out_path)
        durations[shot_id] = {
            "file": out_path.name,
            "duration_s": round(dur, 3),
            "storyboard_duration_s": shot.get("duration_s"),
            "provider": cfg.provider,
            "cache_hit": False,
        }
        print(f"[OK] {shot_id} ({cfg.provider}) -> {out_path.name} ({dur:.2f}s, {latency:.2f}s)")

    durations_path = narration_dir / "durations.json"
    summary = {
        "provider": active_provider,
        "total_duration_s": round(sum(item["duration_s"] for item in durations.values()), 3),
        "shots": durations,
    }
    durations_path.write_text(json.dumps(summary, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(f"Wrote {durations_path} (total speech: {summary['total_duration_s']:.2f}s).")
    return durations_path


def build_parser() -> argparse.ArgumentParser:
    """Build the command-line argument parser for the narration stage."""
    parser = argparse.ArgumentParser(
        description="Generate Amharic narration WAVs and measure durations.",
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
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    """Parse narration CLI flags and run the narration stage."""
    args = build_parser().parse_args(list(argv) if argv is not None else None)
    run_narration(
        shot_ids=parse_shots_arg(args.shots),
        provider_override=args.provider,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
