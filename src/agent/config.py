"""OpenAI configuration helpers for the calendar agent."""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any

import tomllib
from dotenv import load_dotenv
from openai import AsyncOpenAI

DEFAULT_SYSTEM_PROMPT = (
    "You are a concise calendar assistant. Answer clearly and keep replies practical."
)
DEFAULT_MODEL = "gpt-5.4"


@dataclass(frozen=True)
class OpenAISettings:
    """Runtime settings for OpenAI requests."""

    api_key: str
    model: str = DEFAULT_MODEL
    base_url: str | None = None
    system_prompt: str = DEFAULT_SYSTEM_PROMPT
    timeout: float = 30.0


def get_openai_settings(codex_dir: Path | None = None) -> OpenAISettings:
    """Load OpenAI settings from the environment, then fall back to ~/.codex."""
    load_dotenv()

    codex_dir = codex_dir or Path.home() / ".codex"
    codex_auth = _read_json(codex_dir / "auth.json")
    codex_config = _read_toml(codex_dir / "config.toml")
    provider_config = codex_config.get("model_providers", {}).get("OpenAI", {})

    api_key = os.getenv("OPENAI_API_KEY") or codex_auth.get("OPENAI_API_KEY")
    if not api_key:
        raise RuntimeError(
            "Missing OPENAI_API_KEY. Set it in the environment or ~/.codex/auth.json."
        )

    model = os.getenv("OPENAI_MODEL") or codex_config.get("model") or DEFAULT_MODEL
    base_url = os.getenv("OPENAI_BASE_URL") or provider_config.get("base_url")
    system_prompt = os.getenv("OPENAI_SYSTEM_PROMPT") or DEFAULT_SYSTEM_PROMPT
    timeout = float(os.getenv("OPENAI_TIMEOUT", "30"))

    return OpenAISettings(
        api_key=api_key,
        model=model,
        base_url=base_url,
        system_prompt=system_prompt,
        timeout=timeout,
    )


def resolve_openai_settings(
    *,
    model: str | None = None,
    system_prompt: str | None = None,
    codex_dir: Path | None = None,
) -> OpenAISettings:
    """Return base settings with optional runtime overrides."""
    settings = get_openai_settings(codex_dir=codex_dir)
    return replace(
        settings,
        model=model or settings.model,
        system_prompt=system_prompt or settings.system_prompt,
    )


def build_openai_client(settings: OpenAISettings) -> AsyncOpenAI:
    """Create an async OpenAI client from resolved settings."""
    return AsyncOpenAI(
        api_key=settings.api_key,
        base_url=settings.base_url,
        timeout=settings.timeout,
    )


def _read_json(path: Path) -> dict[str, Any]:
    """Read a JSON file if it exists, otherwise return an empty mapping."""
    if not path.exists():
        return {}

    with path.open("r", encoding="utf-8") as file:
        data = json.load(file)

    return data if isinstance(data, dict) else {}


def _read_toml(path: Path) -> dict[str, Any]:
    """Read a TOML file if it exists, otherwise return an empty mapping."""
    if not path.exists():
        return {}

    with path.open("rb") as file:
        data = tomllib.load(file)

    return data if isinstance(data, dict) else {}
