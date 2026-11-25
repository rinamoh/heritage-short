"""Command-line entrypoint for validating and running the Heritage Short pipeline."""

import argparse
from collections.abc import Sequence
import importlib
import json
import sys

import jsonschema

from pipeline.common import config

STAGES: tuple[str, ...] = ("keyframes", "narration", "shots", "assemble")


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
    """Parse CLI arguments and run storyboard validation (stages not wired yet)."""
    parser = build_parser()
    args = parser.parse_args(list(argv) if argv is not None else None)

    exit_code = run_validation()
    if exit_code != 0:
        return exit_code

    if args.export_kaggle_jobs:
        print("Kaggle job export is not implemented yet; validation completed.")
    elif args.stage:
        print(f"Stage '{args.stage}' is not implemented yet; validation completed.")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
