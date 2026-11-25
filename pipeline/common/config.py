"""Project paths and secret configuration loaded from the local .env file."""

from dataclasses import dataclass, field
import os
from pathlib import Path

from dotenv import load_dotenv

ROOT_DIR: Path = Path(__file__).resolve().parents[2]
ENV_PATH: Path = ROOT_DIR / ".env"
STORYBOARD_PATH: Path = ROOT_DIR / "storyboard.json"
SCHEMA_PATH: Path = ROOT_DIR / "schema" / "storyboard.schema.json"
OUTPUTS_DIR: Path = ROOT_DIR / "outputs"
RUNS_LOG_PATH: Path = ROOT_DIR / "runs.jsonl"
KAGGLE_JOBS_DIR: Path = ROOT_DIR / "kaggle" / "jobs"


@dataclass(frozen=True)
class Settings:
    """Container for API credentials loaded from .env without exposing secrets in repr."""

    gemini_api_key: str = field(default="", repr=False)
    cloudflare_account_id: str = field(default="", repr=False)
    cloudflare_api_token: str = field(default="", repr=False)
    addis_api_key: str = field(default="", repr=False)


def load_env(env_path: Path = ENV_PATH) -> None:
    """Load environment variables from the given .env file if it exists."""
    if env_path.is_file():
        load_dotenv(dotenv_path=env_path, override=False)


def get_secret(name: str, required: bool = False) -> str:
    """Read a secret value from the environment after loading .env, without logging it."""
    load_env()
    value = os.environ.get(name, "").strip()
    if required and not value:
        raise ValueError(f"Missing required environment variable: {name}")
    return value


def load_settings(env_path: Path = ENV_PATH) -> Settings:
    """Load all provider credentials from .env and return a Settings instance."""
    load_env(env_path)
    return Settings(
        gemini_api_key=os.environ.get("GEMINI_API_KEY", "").strip(),
        cloudflare_account_id=os.environ.get("CLOUDFLARE_ACCOUNT_ID", "").strip(),
        cloudflare_api_token=os.environ.get("CLOUDFLARE_API_TOKEN", "").strip(),
        addis_api_key=os.environ.get("ADDIS_API_KEY", "").strip(),
    )


def stage_output_dir(stage: str, create: bool = True) -> Path:
    """Return the output directory for a pipeline stage, creating it if requested."""
    path = OUTPUTS_DIR / stage
    if create:
        path.mkdir(parents=True, exist_ok=True)
    return path
