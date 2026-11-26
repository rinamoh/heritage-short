"""Reference sheets and keyframes with FLUX.2 klein 4B on Cloudflare Workers AI.

Input schema (width, height, seed, input_image_0..3; steps fixed at 4):
https://developers.cloudflare.com/changelog/post/2026-01-15-flux-2-klein-4b-workers-ai/
"""

import base64
from dataclasses import dataclass
import io
import json
import math
from pathlib import Path
import time
from typing import Any

from PIL import Image
import requests

from pipeline.common import cache, config, log, retry

PROVIDER: str = "cloudflare"
MODEL: str = "@cf/black-forest-labs/flux-2-klein-4b"
API_URL: str = "https://api.cloudflare.com/client/v4/accounts/{account}/ai/run/" + MODEL
TIMEOUT_S: float = 180.0

# The API accepts 256-1920 per side. 1088 x 1920 is the nearest multiple of 16 to 9:16
# that covers the 1080 x 1920 film without upscaling.
KEYFRAME_SIZE: tuple[int, int] = (1088, 1920)
# References are shrunk before use, so they are generated small to save the free allowance.
REFSHEET_SIZE: tuple[int, int] = (576, 1024)
# Reference images must be smaller than 512 x 512.
REF_MAX_SIDE: int = 511

# List prices per 512 x 512 tile; how partial tiles round is not documented, so this is an estimate.
USD_PER_OUTPUT_TILE: float = 0.000287
USD_PER_INPUT_TILE: float = 0.000059


class CloudflareError(RuntimeError):
    """A failed Cloudflare request; status_code lets the retry helper classify it."""

    def __init__(self, message: str, status_code: int | None = None) -> None:
        super().__init__(message)
        self.status_code = status_code


@dataclass(frozen=True)
class ImageJob:
    """Everything needed to generate, cache and log one image."""

    stage: str
    item_id: str
    prompt: str
    seed: int
    out_dir: Path
    size: tuple[int, int]
    reference: Path | None = None


def join_prompt(*parts: str) -> str:
    """Join the non-empty prompt parts into one prompt."""
    cleaned = [part.strip().rstrip(".,;") for part in parts]
    return ". ".join(part for part in cleaned if part)


def look_by_id(storyboard: dict[str, Any], look_id: str) -> dict[str, Any]:
    """Return the character look with this id."""
    for look in storyboard["character"]["looks"]:
        if look["id"] == look_id:
            return look
    raise ValueError(f"Look {look_id} is not in character.looks")


def refsheet_prompt(storyboard: dict[str, Any], look: dict[str, Any]) -> str:
    """Build the reference-sheet prompt for one look."""
    return join_prompt(
        storyboard["style_block"],
        storyboard["character"]["base"],
        look["clothing"],
        look["carries"],
        storyboard["character"]["refsheet"]["suffix"],
    )


def shot_prompt(storyboard: dict[str, Any], shot: dict[str, Any]) -> str:
    """Build a keyframe prompt; the character text is added only for shots with a look."""
    person: tuple[str, ...] = ()
    if shot["look"] is not None:
        look = look_by_id(storyboard, shot["look"])
        character = storyboard["character"]
        person = (character["base"], look["clothing"], look["carries"], character["shot_suffix"])
    style = storyboard["style_block"]
    no_text = storyboard["no_text_suffix"]
    if no_text.lower() in style.lower():
        no_text = ""
    return join_prompt(style, *person, shot["keyframe"]["prompt"], no_text)


def reference_path(storyboard: dict[str, Any], look_id: str) -> Path:
    """Return the chosen reference image for a look, or raise a clear error."""
    ref_image = look_by_id(storyboard, look_id)["ref_image"]
    if not ref_image:
        raise ValueError(
            f"Look {look_id} has no ref_image yet. Run --stage refsheet, pick one, and set "
            f'character.looks[{look_id}].ref_image in storyboard.json, e.g. "outputs/refs/{look_id}_1.png".'
        )
    path = (config.ROOT_DIR / ref_image).resolve()
    # ETHICS.md: no family photographs are uploaded, so only generated references are allowed.
    if not path.is_relative_to((config.OUTPUTS_DIR / "refs").resolve()):
        raise ValueError(f"Look {look_id}: ref_image must be a generated file in outputs/refs, got {ref_image}")
    if not path.is_file():
        raise ValueError(f"Look {look_id}: ref_image {ref_image} does not exist")
    return path


def shrink_reference(path: Path) -> tuple[bytes, tuple[int, int]]:
    """Return the reference as PNG bytes with both sides under 512 px, plus its new size."""
    with Image.open(path) as image:
        small = image.convert("RGB")
    small.thumbnail((REF_MAX_SIDE, REF_MAX_SIDE), Image.Resampling.LANCZOS)
    buffer = io.BytesIO()
    small.save(buffer, format="PNG")
    return buffer.getvalue(), small.size


def job_cache_key(job: ImageJob) -> str:
    """Hash prompt, seed, model, size and the reference file's contents."""
    params: dict[str, Any] = {"width": job.size[0], "height": job.size[1]}
    if job.reference is not None:
        params["ref_max_side"] = REF_MAX_SIDE
    inputs = [job.reference] if job.reference is not None else None
    return cache.build_cache_key(MODEL, prompt=job.prompt, seed=job.seed, params=params, input_files=inputs)


def estimate_cost_usd(size: tuple[int, int], reference_size: tuple[int, int] | None) -> float:
    """Estimate the list price of one request from the number of 512 px tiles."""
    cost = math.ceil(size[0] / 512) * math.ceil(size[1] / 512) * USD_PER_OUTPUT_TILE
    if reference_size is not None:
        width, height = reference_size
        cost += math.ceil(width / 512) * math.ceil(height / 512) * USD_PER_INPUT_TILE
    return round(cost, 6)


def _decode_image(response: requests.Response) -> bytes:
    """Return the image bytes from a Workers AI response."""
    if "application/json" not in response.headers.get("content-type", "").lower():
        return response.content
    payload = response.json()
    result = payload.get("result", payload)
    encoded = result.get("image") if isinstance(result, dict) else None
    if not encoded:
        raise CloudflareError(f"No image in response: {payload.get('errors')}")
    return base64.b64decode(encoded.split(",", 1)[-1])


def request_image(job: ImageJob, reference_png: bytes | None, account: str, token: str) -> bytes:
    """Make one multipart/form-data request and return the image bytes."""
    fields: list[tuple[str, tuple[Any, ...]]] = [
        ("prompt", (None, job.prompt)),
        ("width", (None, str(job.size[0]))),
        ("height", (None, str(job.size[1]))),
        ("seed", (None, str(job.seed))),
    ]
    if reference_png is not None:
        fields.append(("input_image_0", ("reference.png", reference_png, "image/png")))
    response = requests.post(
        API_URL.format(account=account),
        headers={"Authorization": f"Bearer {token}"},
        files=fields,
        timeout=TIMEOUT_S,
    )
    if response.status_code != 200:
        # Not raise_for_status(): its message contains the URL, which holds the account id.
        raise CloudflareError(f"HTTP {response.status_code}: {response.text[:300]}", response.status_code)
    return _decode_image(response)


def save_png(image_bytes: bytes, path: Path) -> tuple[int, int]:
    """Write the image as PNG without losing provenance metadata, and return its size."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with Image.open(io.BytesIO(image_bytes)) as image:
        size = image.size
        if image.format == "PNG":
            path.write_bytes(image_bytes)
            return size
        # Converting would drop embedded metadata, so the original is kept next to the PNG.
        suffix = (image.format or "bin").lower().replace("jpeg", "jpg")
        path.with_name(f"{path.stem}.orig.{suffix}").write_bytes(image_bytes)
        image.save(path, format="PNG")
    return size


def _read_index(out_dir: Path) -> dict[str, Any]:
    """Read the folder's index.json (what each current image was generated from)."""
    path = out_dir / "index.json"
    return json.loads(path.read_text(encoding="utf-8")) if path.is_file() else {}


def _record(out_dir: Path, item_id: str, file_name: str, key: str) -> None:
    """Record the current file and cache key for a shot or reference option."""
    index = _read_index(out_dir)
    index[item_id] = {"file": file_name, "key": key}
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "index.json").write_text(json.dumps(index, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def generate_image(job: ImageJob, out_path: Path, key: str, log_path: Path) -> retry.CallResult:
    """Call Cloudflare with retries, save the image, and log the call."""
    settings = config.load_settings()
    account, token = settings.cloudflare_account_id, settings.cloudflare_api_token
    if not account or not token:
        raise ValueError("Missing CLOUDFLARE_ACCOUNT_ID or CLOUDFLARE_API_TOKEN in .env")
    reference_png, reference_size = (None, None)
    if job.reference is not None:
        reference_png, reference_size = shrink_reference(job.reference)

    started = time.monotonic()
    result = retry.run_with_retry(lambda: request_image(job, reference_png, account, token))
    error = result.error
    size: tuple[int, int] | None = None
    if result.ok:
        try:
            size = save_png(result.value, out_path)
        except OSError as exc:
            error = f"{type(exc).__name__}: {exc}"
    if error is not None:
        error = error.replace(account, "<account>").replace(token, "<token>")

    log.log_call(
        stage=job.stage,
        shot_id=job.item_id,
        provider=PROVIDER,
        model=MODEL,
        params=_log_params(job, key, out_path, size, reference_size, result.attempts),
        seed=job.seed,
        latency_s=time.monotonic() - started,
        cost_usd_equiv=estimate_cost_usd(job.size, reference_size) if error is None else 0.0,
        status="ok" if error is None else "error",
        error=error,
        log_path=log_path,
    )
    return retry.CallResult(ok=error is None, error=error, attempts=result.attempts, status_code=result.status_code)


def _log_params(
    job: ImageJob,
    key: str,
    out_path: Path,
    size: tuple[int, int] | None,
    reference_size: tuple[int, int] | None,
    attempts: int,
) -> dict[str, Any]:
    """Build the params object of a runs.jsonl line."""
    return {
        "prompt": job.prompt,
        "width": job.size[0],
        "height": job.size[1],
        "returned_size": f"{size[0]}x{size[1]}" if size else None,
        "reference_used": job.reference is not None,
        "reference_file": job.reference.name if job.reference else None,
        "reference_sent_size": f"{reference_size[0]}x{reference_size[1]}" if reference_size else None,
        "cache_key": key[:12],
        "output": out_path.name,
        "attempts": attempts,
    }


def run_job(job: ImageJob, out_path: Path, key: str, log_path: Path) -> retry.CallResult:
    """Skip the call if this exact image exists; otherwise generate it."""
    if cache.get_cached(out_path) is not None:
        log.log_call(
            stage=job.stage,
            shot_id=job.item_id,
            provider=PROVIDER,
            model=MODEL,
            params=_log_params(job, key, out_path, None, None, 0),
            seed=job.seed,
            cache_hit=True,
            log_path=log_path,
        )
        print(f"[CACHED] {job.item_id}: {out_path}")
        result = retry.CallResult(ok=True)
    else:
        result = generate_image(job, out_path, key, log_path)
        print(f"[OK] {job.item_id}: {out_path}" if result.ok else f"[FAIL] {job.item_id}: {result.error}")
    if result.ok:
        _record(job.out_dir, job.item_id, out_path.name, key)
    return result


def _set_aside_stale(job: ImageJob, out_path: Path, key: str) -> None:
    """Rename a reference made from older inputs, so it is regenerated but never lost."""
    if not out_path.is_file():
        return
    recorded = _read_index(job.out_dir).get(job.item_id, {}).get("key")
    if recorded == key:
        return
    old = out_path.with_name(f"{out_path.stem}_old_{(recorded or cache.hash_file(out_path))[:12]}.png")
    out_path.replace(old)
    print(f"[NOTE] {job.item_id}: inputs changed; the previous image is now {old.name}")


def _quota_reached(result: retry.CallResult) -> bool:
    """Stop a run at the first 429: the daily free allocation is probably used up."""
    if result.status_code != 429:
        return False
    print("[STOP] Cloudflare returned 429. Re-run later; finished images are cached.")
    return True


def run_refsheet(
    storyboard_path: Path = config.STORYBOARD_PATH,
    log_path: Path = config.RUNS_LOG_PATH,
) -> list[str]:
    """Generate one option per look and seed into outputs/refs and return the ones that failed."""
    storyboard = json.loads(storyboard_path.read_text(encoding="utf-8"))
    out_dir = config.stage_output_dir("refs")
    jobs = [
        ImageJob(
            "refsheet", f"{look['id']}_{seed}", refsheet_prompt(storyboard, look), seed, out_dir, REFSHEET_SIZE
        )
        for look in storyboard["character"]["looks"]
        for seed in storyboard["character"]["refsheet"]["seeds"]
    ]
    failed: list[str] = []
    for job in jobs:
        out_path = out_dir / f"{job.item_id}.png"
        key = job_cache_key(job)
        _set_aside_stale(job, out_path, key)
        result = run_job(job, out_path, key, log_path)
        if not result.ok:
            failed.append(job.item_id)
            if _quota_reached(result):
                break
    print(f"Reference options are in {out_dir}. Set each look's ref_image in storyboard.json to your pick.")
    return failed


def _keyframe_jobs(storyboard: dict[str, Any], shot_id: str | None, no_ref: bool) -> list[ImageJob]:
    """Build the keyframe jobs, checking every needed reference before any call is made."""
    shots = storyboard["shots"]
    if shot_id is not None:
        shots = [shot for shot in shots if shot["id"] == shot_id]
        if not shots:
            raise ValueError(f"No shot with id {shot_id}")
    if no_ref:
        # E5 compares with and without a reference, so shots without a look have nothing to compare.
        shots = [shot for shot in shots if shot["look"] is not None]
        if not shots:
            raise ValueError(f"--no-ref only applies to shots with a look; {shot_id} has none")

    out_dir = config.stage_output_dir("keyframes")
    if no_ref:
        out_dir = out_dir / "e5"
    jobs: list[ImageJob] = []
    for shot in shots:
        reference = None
        if shot["look"] is not None and not no_ref:
            reference = reference_path(storyboard, shot["look"])
        prompt = shot_prompt(storyboard, shot)
        seed = int(shot["keyframe"]["seed"])
        jobs.append(ImageJob("keyframes", shot["id"], prompt, seed, out_dir, KEYFRAME_SIZE, reference))
    return jobs


def run_keyframes(
    shot_id: str | None = None,
    no_ref: bool = False,
    storyboard_path: Path = config.STORYBOARD_PATH,
    log_path: Path = config.RUNS_LOG_PATH,
) -> list[str]:
    """Generate keyframes (or the E5 no-reference variants) and return the shots that failed."""
    storyboard = json.loads(storyboard_path.read_text(encoding="utf-8"))
    failed: list[str] = []
    for job in _keyframe_jobs(storyboard, shot_id, no_ref):
        key = job_cache_key(job)
        out_path = cache.cache_path(job.out_dir, job.item_id, key, "png")
        result = run_job(job, out_path, key, log_path)
        if not result.ok:
            failed.append(job.item_id)
            if _quota_reached(result):
                break
    return failed
