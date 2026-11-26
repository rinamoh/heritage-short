"""Validate storyboard.json against storyboard.schema.json and domain rules."""

from collections.abc import Iterable
import json
from pathlib import Path
import sys
from typing import Any

from jsonschema import Draft202012Validator

from pipeline.common import config

MAX_SUBTITLE_LINE_CHARS: int = 42


def format_json_path(parts: Iterable[str | int]) -> str:
    """Format a sequence of JSON keys and array indices as a JSONPath string."""
    path = "$"
    for part in parts:
        if isinstance(part, int):
            path += f"[{part}]"
        else:
            path += f".{part}"
    return path


def load_json_file(path: Path) -> Any:
    """Read and parse a UTF-8 JSON file from disk."""
    with path.open("r", encoding="utf-8") as handle:
        return json.load(handle)


def collect_schema_errors(storyboard: Any, schema: dict[str, Any]) -> list[str]:
    """Validate storyboard data against the draft 2020-12 JSON schema and list all errors."""
    validator = Draft202012Validator(schema)
    errors = sorted(validator.iter_errors(storyboard), key=lambda err: list(err.absolute_path))
    return [f"{format_json_path(err.absolute_path)}: {err.message}" for err in errors]


def collect_domain_errors(storyboard: dict[str, Any]) -> list[str]:
    """Check look references, subtitle line lengths, unique shot IDs, and silent shot lengths."""
    errors: list[str] = []

    character = storyboard.get("character") or {}
    looks = character.get("looks") or []
    look_ids = {
        look.get("id")
        for look in looks
        if isinstance(look, dict) and isinstance(look.get("id"), str)
    }

    shots = storyboard.get("shots") or []
    seen_ids: set[str] = set()

    for idx, shot in enumerate(shots):
        if not isinstance(shot, dict):
            continue

        shot_id = shot.get("id")
        if isinstance(shot_id, str):
            if shot_id in seen_ids:
                errors.append(f"{format_json_path(['shots', idx, 'id'])}: duplicate shot id {shot_id!r}")
            seen_ids.add(shot_id)

        look = shot.get("look")
        if look is not None and look not in look_ids:
            errors.append(
                f"{format_json_path(['shots', idx, 'look'])}: look {look!r} not found in character.looks"
            )

        narration = shot.get("narration")
        if isinstance(narration, dict) and narration.get("segments") == [] and "duration_s" not in shot:
            errors.append(f"{format_json_path(['shots', idx])}: a silent shot needs duration_s")

        subtitles = shot.get("subtitle_en")
        if isinstance(subtitles, list):
            for cue_idx, cue in enumerate(subtitles):
                if not isinstance(cue, list):
                    continue
                for line_idx, line in enumerate(cue):
                    if isinstance(line, str) and len(line) > MAX_SUBTITLE_LINE_CHARS:
                        errors.append(
                            f"{format_json_path(['shots', idx, 'subtitle_en', cue_idx, line_idx])}: "
                            f"subtitle line has {len(line)} chars (max {MAX_SUBTITLE_LINE_CHARS})"
                        )

    return errors


def validate_storyboard(
    storyboard_path: Path = config.STORYBOARD_PATH,
    schema_path: Path = config.SCHEMA_PATH,
) -> int:
    """Validate storyboard.json against schema and domain rules; print results and return exit code."""
    if not schema_path.is_file():
        print(f"$.schema: missing schema file at {schema_path}", file=sys.stderr)
        return 1
    if not storyboard_path.is_file():
        print(f"$: missing storyboard file at {storyboard_path}", file=sys.stderr)
        return 1

    try:
        schema = load_json_file(schema_path)
    except json.JSONDecodeError as exc:
        print(f"$.schema: invalid JSON ({exc})", file=sys.stderr)
        return 1

    try:
        storyboard = load_json_file(storyboard_path)
    except json.JSONDecodeError as exc:
        print(f"$: invalid JSON in {storyboard_path.name} ({exc})", file=sys.stderr)
        return 1

    errors = collect_schema_errors(storyboard, schema)
    if isinstance(storyboard, dict):
        errors.extend(collect_domain_errors(storyboard))

    if errors:
        for err in errors:
            print(err, file=sys.stderr)
        return 1

    shots = storyboard.get("shots", [])
    print(
        f"VALID: {storyboard_path.name} passed schema and domain checks "
        f"({len(shots)} shots; total length is checked by the radio stage)."
    )
    return 0


def main() -> int:
    """CLI entrypoint for validating storyboard.json."""
    return validate_storyboard()


if __name__ == "__main__":
    raise SystemExit(main())
