"""Command-line entrypoint for validating and running the Heritage Short pipeline."""

import argparse
from collections.abc import Sequence
import importlib
import json
import sys

import jsonschema

from pipeline.common import config

STAGES: tuple[str, ...] = (
    "refsheet",
    "keyframes",
    "narration",
    "shots",
    "assemble",
    "radio",
    "music-plan",
    "music-import",
)


def build_parser() -> argparse.ArgumentParser:
    """Build the command-line argument parser for the pipeline runner."""
    parser = argparse.ArgumentParser(
        description="Validate storyboard.json and run the Heritage Short pipeline.",
    )
    parser.add_argument(
        "--stage",
        choices=STAGES,
        default=None,
        help="Run only one pipeline stage instead of the full pipeline.",
    )
    parser.add_argument(
        "--export-kaggle-jobs",
        action="store_true",
        help="Export Kaggle GPU job specifications to kaggle/jobs/.",
    )
    parser.add_argument(
        "--shots",
        default=None,
        help="Optional comma-separated shot IDs to pass to a stage (e.g. s03,s10).",
    )
    parser.add_argument(
        "--shot",
        default=None,
        help="keyframes: generate only this shot (e.g. s04).",
    )
    parser.add_argument(
        "--no-ref",
        action="store_true",
        help="keyframes: experiment E5, no reference image; saves to outputs/keyframes/e5/.",
    )
    parser.add_argument(
        "--provider",
        choices=("gemini", "addis"),
        default=None,
        help="Override voice.provider for the narration stage without editing storyboard.json.",
    )
    parser.add_argument(
        "--allow-calls",
        type=int,
        default=None,
        help="Narration: allow this many Gemini TTS calls (default limit 9).",
    )
    parser.add_argument(
        "--choose",
        type=int,
        default=None,
        help="music-import: set music.chosen to this seed.",
    )
    return parser


def run_validation() -> int:
    """Validate storyboard.json against schema/storyboard.schema.json and return an exit code."""
    try:
        validate_mod = importlib.import_module("pipeline.validate")
    except ModuleNotFoundError:
        validate_mod = None

    if validate_mod is not None:
        for fn_name in ("validate_storyboard", "main"):
            fn = getattr(validate_mod, fn_name, None)
            if callable(fn):
                result = fn()
                if isinstance(result, int):
                    return result
                return 0

    if not config.SCHEMA_PATH.is_file():
        print(f"Validation skipped/failed: missing schema at {config.SCHEMA_PATH}", file=sys.stderr)
        return 1
    if not config.STORYBOARD_PATH.is_file():
        print(f"Validation skipped/failed: missing storyboard at {config.STORYBOARD_PATH}", file=sys.stderr)
        return 1

    with config.SCHEMA_PATH.open("r", encoding="utf-8") as schema_file:
        schema = json.load(schema_file)
    with config.STORYBOARD_PATH.open("r", encoding="utf-8") as storyboard_file:
        storyboard = json.load(storyboard_file)

    jsonschema.validate(instance=storyboard, schema=schema)
    print(f"Validated {config.STORYBOARD_PATH.name} against {config.SCHEMA_PATH.name}.")
    return 0


def main(argv: Sequence[str] | None = None) -> int:
    """Parse CLI arguments, run validation first, and execute the requested stage."""
    parser = build_parser()
    args = parser.parse_args(list(argv) if argv is not None else None)

    exit_code = run_validation()
    if exit_code != 0:
        return exit_code

    if args.export_kaggle_jobs:
        print("Kaggle job export is not implemented yet; validation completed.")
    elif args.stage in ("refsheet", "keyframes"):
        from pipeline import keyframes

        try:
            if args.stage == "refsheet":
                failed = keyframes.run_refsheet()
            else:
                failed = keyframes.run_keyframes(shot_id=args.shot, no_ref=args.no_ref)
        except ValueError as exc:
            print(f"[ABORT] {exc}")
            return 2
        if failed:
            print(f"Failed: {', '.join(failed)}")
            return 1
    elif args.stage == "narration":
        from pipeline import narration

        shot_ids = narration.parse_shots_arg(args.shots)
        try:
            missing = narration.run_narration(
                shot_ids=shot_ids,
                provider_override=args.provider,
                allow_calls=args.allow_calls,
            )
        except narration.QuotaGuardError as exc:
            print(f"[ABORT] {exc}")
            return 2
        if missing:
            return 1
    elif args.stage == "radio":
        from pipeline import assemble

        if assemble.run_radio() is None:
            return 1
    elif args.stage == "music-plan":
        from pipeline import music

        music.plan_music()
    elif args.stage == "music-import":
        from pipeline import music

        music.import_music(choose=args.choose)
    elif args.stage:
        print(f"Stage '{args.stage}' is not implemented yet; validation completed.")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
