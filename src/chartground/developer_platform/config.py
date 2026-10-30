"""Shared root-relative configuration for developer-platform entry points."""

import os
from dataclasses import dataclass, field
from pathlib import Path

from dotenv import load_dotenv


PROJECT_ROOT = Path(__file__).resolve().parents[3]


@dataclass(frozen=True)
class Configuration:
    api_key: str | None = field(repr=False)
    model: str | None
    max_tokens: int = 4096


def load_configuration() -> Configuration:
    load_dotenv(PROJECT_ROOT / ".env", override=False)
    max_tokens = int(os.getenv("ANTHROPIC_MAX_TOKENS", "4096"))
    if not 256 <= max_tokens <= 8192:
        raise ValueError("ANTHROPIC_MAX_TOKENS must be between 256 and 8192.")
    return Configuration(
        api_key=os.getenv("ANTHROPIC_API_KEY"),
        model=os.getenv("ANTHROPIC_MODEL"),
        max_tokens=max_tokens,
    )
