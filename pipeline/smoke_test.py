"""Smoke test making one live call per provider and logging results to runs.jsonl."""

import argparse
import base64
from collections.abc import Sequence
from dataclasses import dataclass
import io
from pathlib import Path
import time
from typing import Any
import wave

import addisai
from google import genai
from PIL import Image
import requests

from pipeline.common import config, log

GEMINI_TEXT_MODEL: str = "gemini-3.8-flash"
GEMINI_TTS_PRIMARY_MODEL: str = "gemini-3.8-flash-lite-tts"
GEMINI_TTS_PROBE_MODEL: str = "gemini-2.5-flash-preview-tts"
GEMINI_TTS_VOICE: str = "Kore"
GEMINI_TTS_STYLE: str = "warm, calm, clear narration"
ADDIS_MODEL_ID: str = "addisai-voice"
ADDIS_VOICE_ID: str = "am-hamen"
ADDIS_LANGUAGE: str = "am"
ADDIS_OUTPUT_FORMAT: str = "wav_44100"
CLOUDFLARE_MODEL: str = "@cf/black-forest-labs/flux-2-klein-4b"

AMHARIC_SAMPLE_TEXT: str = "ሰላም፣ ይህ የድምፅ ሙከራ ነው።"
IMAGE_SAMPLE_PROMPT: str = (
    "A warm kerosene lamp glowing on a bare wooden table at night, "
    "film grain, soft warm light, cinematic still."
)
TTS_COOLDOWN_SECONDS: float = 21.0


@dataclass(frozen=True)
class SmokeResult:
    """Outcome of a single provider smoke check."""

    name: str
    passed: bool
    optional: bool
    detail: str
    latency_s: float


def _ensure_wav_bytes(audio_bytes: bytes, sample_rate: int = 24000) -> bytes:
    """Wrap raw 16-bit mono PCM in a WAV header if RIFF header is not already present."""
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


def _call_gemini_tts(
    client: genai.Client,
    model: str,
    text: str,
    voice: str,
    style: str,
) -> bytes:
    """Invoke Gemini TTS via client.interactions.create and return WAV bytes."""
    interaction = client.interactions.create(
        model=model,
        input=[
            {
                "type": "user_input",
                "content": [
                    {
                        "type": "text",
                        "text": text,
                        "annotations": [{"type": "speech_metadata", "style": style}],
                    }
                ],
            }
        ],
        response_format={"type": "audio"},
        generation_config={"speech_config": [{"voice": voice}]},
    )
    errors = getattr(interaction, "errors", None)
    if errors:
        raise RuntimeError(f"Interaction errors: {errors}")
    return _ensure_wav_bytes(_extract_interaction_audio(interaction))


def test_gemini_text(api_key: str) -> SmokeResult:
    """Run one Gemini text generation call on gemini-3.8-flash and log the result."""
    name = f"gemini_text ({GEMINI_TEXT_MODEL})"
    prompt = "Say hello in Amharic"
    params = {"prompt": prompt}
    if not api_key:
        err = "Missing GEMINI_API_KEY in .env"
        log.log_call("smoke", "smoke_gemini_text", "gemini", GEMINI_TEXT_MODEL, params=params, status="error", error=err)
        return SmokeResult(name=name, passed=False, optional=False, detail=err, latency_s=0.0)

    started = time.monotonic()
    try:
        client = genai.Client(api_key=api_key)
        response = client.models.generate_content(model=GEMINI_TEXT_MODEL, contents=prompt)
        latency = time.monotonic() - started
        text = (getattr(response, "text", None) or "").strip()
        if not text:
            raise ValueError("Empty text response from Gemini.")
        log.log_call(
            stage="smoke",
            shot_id="smoke_gemini_text",
            provider="gemini",
            model=GEMINI_TEXT_MODEL,
            params=params,
            latency_s=latency,
            status="ok",
        )
        return SmokeResult(name=name, passed=True, optional=False, detail=text, latency_s=latency)
    except Exception as exc:
        latency = time.monotonic() - started
        err = f"{type(exc).__name__}: {exc}"
        log.log_call(
            stage="smoke",
            shot_id="smoke_gemini_text",
            provider="gemini",
            model=GEMINI_TEXT_MODEL,
            params=params,
            latency_s=latency,
            status="error",
            error=err,
        )
        return SmokeResult(name=name, passed=False, optional=False, detail=err, latency_s=latency)


def test_gemini_tts(
    api_key: str,
    model: str,
    shot_id: str,
    out_path: Path,
    optional: bool = False,
) -> SmokeResult:
    """Run one Gemini TTS call, save WAV output if successful, and log the call."""
    name = f"gemini_tts ({model})"
    params = {
        "voice": GEMINI_TTS_VOICE,
        "style": GEMINI_TTS_STYLE,
        "text_chars": len(AMHARIC_SAMPLE_TEXT),
    }
    if not api_key:
        err = "Missing GEMINI_API_KEY in .env"
        log.log_call("smoke", shot_id, "gemini", model, params=params, status="error", error=err)
        return SmokeResult(name=name, passed=False, optional=optional, detail=err, latency_s=0.0)

    started = time.monotonic()
    try:
        client = genai.Client(api_key=api_key, http_options={"api_version": "v1beta"})
        wav_bytes = _call_gemini_tts(
            client=client,
            model=model,
            text=AMHARIC_SAMPLE_TEXT,
            voice=GEMINI_TTS_VOICE,
            style=GEMINI_TTS_STYLE,
        )
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_bytes(wav_bytes)
        latency = time.monotonic() - started
        log.log_call(
            stage="smoke",
            shot_id=shot_id,
            provider="gemini",
            model=model,
            params=params,
            latency_s=latency,
            status="ok",
        )
        detail = f"saved {out_path} ({len(wav_bytes)} bytes)"
        return SmokeResult(name=name, passed=True, optional=optional, detail=detail, latency_s=latency)
    except Exception as exc:
        latency = time.monotonic() - started
        err = f"{type(exc).__name__}: {exc}"
        log.log_call(
            stage="smoke",
            shot_id=shot_id,
            provider="gemini",
            model=model,
            params=params,
            latency_s=latency,
            status="error",
            error=err,
        )
        return SmokeResult(name=name, passed=False, optional=optional, detail=err, latency_s=latency)


def test_addis_tts(api_key: str, out_path: Path) -> SmokeResult:
    """List Amharic voices and generate one Addis AI WAV clip, logging credits and currency."""
    name = f"addisai_tts ({ADDIS_VOICE_ID})"
    base_params: dict[str, Any] = {
        "voice_id": ADDIS_VOICE_ID,
        "language": ADDIS_LANGUAGE,
        "output_format": ADDIS_OUTPUT_FORMAT,
    }
    if not api_key:
        err = "Missing ADDIS_API_KEY in .env"
        log.log_call("smoke", "smoke_addis", "addisai", ADDIS_MODEL_ID, params=base_params, status="error", error=err)
        return SmokeResult(name=name, passed=False, optional=False, detail=err, latency_s=0.0)

    client = addisai.AddisAI(api_key=api_key)
    voice_ids: list[str] = []

    list_started = time.monotonic()
    try:
        voices = client.voices.list(language=ADDIS_LANGUAGE)
        list_latency = time.monotonic() - list_started
        voice_ids = [str(v.get("voice_id") or v.get("id") or "") for v in voices]
        log.log_call(
            stage="smoke",
            shot_id="smoke_addis_voices",
            provider="addisai",
            model="voices.list",
            params={"language": ADDIS_LANGUAGE, "voice_count": len(voices)},
            latency_s=list_latency,
            status="ok",
        )
    except Exception as exc:
        list_latency = time.monotonic() - list_started
        log.log_call(
            stage="smoke",
            shot_id="smoke_addis_voices",
            provider="addisai",
            model="voices.list",
            params={"language": ADDIS_LANGUAGE},
            latency_s=list_latency,
            status="error",
            error=f"{type(exc).__name__}: {exc}",
        )

    gen_started = time.monotonic()
    try:
        clip = client.voice.generate(
            voice_id=ADDIS_VOICE_ID,
            text=AMHARIC_SAMPLE_TEXT,
            language=ADDIS_LANGUAGE,
            output_format=ADDIS_OUTPUT_FORMAT,
        )
        out_path.parent.mkdir(parents=True, exist_ok=True)
        clip.to_file(str(out_path))
        gen_latency = time.monotonic() - gen_started

        usage = clip.usage or {}
        credits_used = usage.get("credits_used")
        currency = usage.get("currency")
        log_params: dict[str, Any] = {
            **base_params,
            "credits_used": credits_used,
            "currency": currency,
            "duration_seconds": clip.duration_seconds,
            "am_voices_found": len(voice_ids),
        }
        log.log_call(
            stage="smoke",
            shot_id="smoke_addis",
            provider="addisai",
            model=ADDIS_MODEL_ID,
            params=log_params,
            latency_s=gen_latency,
            status="ok",
        )
        detail = (
            f"saved {out_path} ({out_path.stat().st_size} bytes), "
            f"credits_used={credits_used} {currency or ''}, "
            f"am_voices={voice_ids}"
        )
        return SmokeResult(name=name, passed=True, optional=False, detail=detail, latency_s=gen_latency)
    except Exception as exc:
        gen_latency = time.monotonic() - gen_started
        err = f"{type(exc).__name__}: {exc}"
        log.log_call(
            stage="smoke",
            shot_id="smoke_addis",
            provider="addisai",
            model=ADDIS_MODEL_ID,
            params={**base_params, "credits_used": None, "currency": None},
            latency_s=gen_latency,
            status="error",
            error=err,
        )
        return SmokeResult(name=name, passed=False, optional=False, detail=err, latency_s=gen_latency)


def _decode_cloudflare_image(response: requests.Response) -> bytes:
    """Decode base64 or binary image bytes from a Cloudflare Workers AI response."""
    content_type = response.headers.get("content-type", "").lower()
    if "application/json" not in content_type:
        return response.content

    payload = response.json()
    if not payload.get("success", True):
        raise RuntimeError(f"Cloudflare API error: {payload.get('errors')}")

    result = payload.get("result")
    if isinstance(result, dict):
        image_b64 = result.get("image") or result.get("data")
    elif isinstance(result, str):
        image_b64 = result
    else:
        image_b64 = None

    if not isinstance(image_b64, str) or not image_b64:
        raise ValueError(f"Unexpected Cloudflare response keys: {list(payload.keys())}")
    if "," in image_b64 and image_b64.startswith("data:"):
        image_b64 = image_b64.split(",", 1)[1]
    return base64.b64decode(image_b64)


def test_cloudflare_flux(account_id: str, api_token: str, out_path: Path) -> SmokeResult:
    """Run one Cloudflare FLUX.2 klein 4B generation call and save smoke.png."""
    name = f"cloudflare_flux ({CLOUDFLARE_MODEL})"
    params = {"prompt": IMAGE_SAMPLE_PROMPT}
    if not account_id or not api_token:
        err = "Missing CLOUDFLARE_ACCOUNT_ID or CLOUDFLARE_API_TOKEN in .env"
        log.log_call("smoke", "smoke_flux", "cloudflare", CLOUDFLARE_MODEL, params=params, status="error", error=err)
        return SmokeResult(name=name, passed=False, optional=False, detail=err, latency_s=0.0)

    url = f"https://api.cloudflare.com/client/v4/accounts/{account_id}/ai/run/{CLOUDFLARE_MODEL}"
    headers = {"Authorization": f"Bearer {api_token}"}

    started = time.monotonic()
    try:
        response = requests.post(
            url,
            headers=headers,
            files={"prompt": (None, IMAGE_SAMPLE_PROMPT)},
            timeout=120,
        )
        response.raise_for_status()
        image_bytes = _decode_cloudflare_image(response)
        with Image.open(io.BytesIO(image_bytes)) as img:
            img_size = img.size
            out_path.parent.mkdir(parents=True, exist_ok=True)
            img.save(out_path, format="PNG")
        latency = time.monotonic() - started
        log.log_call(
            stage="smoke",
            shot_id="smoke_flux",
            provider="cloudflare",
            model=CLOUDFLARE_MODEL,
            params={**params, "size": f"{img_size[0]}x{img_size[1]}"},
            latency_s=latency,
            status="ok",
        )
        detail = f"saved {out_path} ({img_size[0]}x{img_size[1]}, {out_path.stat().st_size} bytes)"
        return SmokeResult(name=name, passed=True, optional=False, detail=detail, latency_s=latency)
    except Exception as exc:
        latency = time.monotonic() - started
        err = f"{type(exc).__name__}: {exc}"
        log.log_call(
            stage="smoke",
            shot_id="smoke_flux",
            provider="cloudflare",
            model=CLOUDFLARE_MODEL,
            params=params,
            latency_s=latency,
            status="error",
            error=err,
        )
        return SmokeResult(name=name, passed=False, optional=False, detail=err, latency_s=latency)


PROVIDER_CHOICES: tuple[str, ...] = (
    "gemini_text",
    "gemini_tts",
    "gemini_tts_probe",
    "addis",
    "cloudflare",
)


def build_parser() -> argparse.ArgumentParser:
    """Build the command-line argument parser for selecting smoke checks."""
    parser = argparse.ArgumentParser(
        description="Run one live smoke check per provider (or a single provider via --only).",
    )
    parser.add_argument(
        "--only",
        choices=PROVIDER_CHOICES,
        default=None,
        help="Run only the specified provider check.",
    )
    return parser


def run_smoke_tests(only: str | None = None) -> list[SmokeResult]:
    """Execute all (or one selected) provider smoke checks safely and return results."""
    settings = config.load_settings()
    narration_dir = config.stage_output_dir("narration")
    keyframes_dir = config.stage_output_dir("keyframes")
    selected = {only} if only is not None else set(PROVIDER_CHOICES)

    results: list[SmokeResult] = []
    if "gemini_text" in selected:
        results.append(test_gemini_text(settings.gemini_api_key))

    tts_primary_end: float | None = None
    if "gemini_tts" in selected:
        results.append(
            test_gemini_tts(
                api_key=settings.gemini_api_key,
                model=GEMINI_TTS_PRIMARY_MODEL,
                shot_id="smoke_gemini",
                out_path=narration_dir / "smoke_gemini.wav",
                optional=False,
            )
        )
        tts_primary_end = time.monotonic()

    if "addis" in selected:
        results.append(test_addis_tts(settings.addis_api_key, narration_dir / "smoke_addis.wav"))

    if "cloudflare" in selected:
        results.append(
            test_cloudflare_flux(
                account_id=settings.cloudflare_account_id,
                api_token=settings.cloudflare_api_token,
                out_path=keyframes_dir / "smoke.png",
            )
        )

    if "gemini_tts_probe" in selected:
        if tts_primary_end is not None:
            elapsed_since_tts = time.monotonic() - tts_primary_end
            if elapsed_since_tts < TTS_COOLDOWN_SECONDS:
                time.sleep(TTS_COOLDOWN_SECONDS - elapsed_since_tts)
        results.append(
            test_gemini_tts(
                api_key=settings.gemini_api_key,
                model=GEMINI_TTS_PROBE_MODEL,
                shot_id="smoke_gemini_25_probe",
                out_path=narration_dir / "smoke_gemini_25_probe.wav",
                optional=True,
            )
        )
    return results


def main(argv: Sequence[str] | None = None) -> int:
    """Parse CLI options, run provider smoke checks, print PASS/FAIL, and exit cleanly."""
    args = build_parser().parse_args(list(argv) if argv is not None else None)
    results = run_smoke_tests(only=args.only)
    required_failures = 0
    for res in results:
        tag = "PASS" if res.passed else "FAIL"
        opt_note = " [optional]" if res.optional else ""
        print(f"[{tag}] {res.name}{opt_note} ({res.latency_s:.2f}s): {res.detail}")
        if not res.passed and not res.optional:
            required_failures += 1
    return 0 if required_failures == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
