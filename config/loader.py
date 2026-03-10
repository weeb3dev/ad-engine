"""Configuration loader and Gemini client factory.

Provides singleton access to the validated Config and a pre-configured
google.genai Client so every module uses the same instances.
"""

from __future__ import annotations

import os
import sys
from functools import lru_cache
from pathlib import Path

from dotenv import load_dotenv
from google import genai

from config.observability import init_observability
from generate.models import Config

load_dotenv()
init_observability()

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
_DEFAULT_CONFIG_PATH = _PROJECT_ROOT / "config" / "config.yaml"


@lru_cache(maxsize=1)
def get_config(path: str | Path | None = None) -> Config:
    """Load, validate, and cache the project configuration.

    Looks for config/config.yaml relative to the project root by default.
    """
    config_path = Path(path) if path else _DEFAULT_CONFIG_PATH
    try:
        return Config.from_yaml(config_path)
    except FileNotFoundError as exc:
        print(f"[config] ERROR: {exc}", file=sys.stderr)
        print(
            "[config] TIP: Run commands from the ad-engine/ project root.",
            file=sys.stderr,
        )
        raise
    except Exception as exc:
        print(
            f"[config] ERROR: Failed to parse config — {exc}",
            file=sys.stderr,
        )
        print(
            "[config] TIP: Validate your YAML syntax and check that all "
            "required fields are present in config/config.yaml.",
            file=sys.stderr,
        )
        raise


def get_gemini_client() -> genai.Client:
    """Return a google.genai Client using the GOOGLE_API_KEY env var."""
    api_key = os.getenv("GOOGLE_API_KEY")
    if not api_key:
        print(
            "[config] ERROR: GOOGLE_API_KEY not set. "
            "Add it to your .env file.",
            file=sys.stderr,
        )
        raise EnvironmentError("GOOGLE_API_KEY environment variable is missing")
    return genai.Client(api_key=api_key)
