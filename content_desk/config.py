"""Settings for the content desk, read from the environment (``DESK_*``)."""

from __future__ import annotations

import ipaddress
import os
from collections.abc import Mapping
from dataclasses import dataclass
from dataclasses import field
from pathlib import Path
from typing import Literal
from urllib.parse import urlparse

Provider = Literal["ollama", "gemini", "stub"]
PROVIDERS: tuple[Provider, ...] = ("ollama", "gemini", "stub")

DEFAULT_OLLAMA_MODEL = "qwen3:4b"
DEFAULT_GEMINI_MODEL = "gemini-3.5-flash"
DEFAULT_OLLAMA_HOST = "http://127.0.0.1:11434"
BUNDLED_SOURCES = Path(__file__).parent / "sources"


class ConfigError(ValueError):
    """A setting is missing or invalid."""


def _int(env: Mapping[str, str], name: str, default: int, low: int, high: int) -> int:
    raw = env.get(name, "").strip()
    if not raw:
        return default
    try:
        value = int(raw)
    except ValueError as exc:
        raise ConfigError(f"{name} must be an integer, got {raw!r}") from exc
    if not low <= value <= high:
        raise ConfigError(f"{name} must be between {low} and {high}, got {value}")
    return value


def _float(env: Mapping[str, str], name: str, default: float, low: float, high: float) -> float:
    raw = env.get(name, "").strip()
    if not raw:
        return default
    try:
        value = float(raw)
    except ValueError as exc:
        raise ConfigError(f"{name} must be a number, got {raw!r}") from exc
    if not low <= value <= high:
        raise ConfigError(f"{name} must be between {low} and {high}, got {value}")
    return value


def is_loopback(url: str) -> bool:
    """True when ``url`` points at this machine (127.0.0.0/8, ::1 or localhost)."""
    host = urlparse(url).hostname or ""
    if host == "localhost":
        return True
    try:
        return ipaddress.ip_address(host).is_loopback
    except ValueError:
        return False


@dataclass(frozen=True)
class Settings:
    """Everything the pipeline needs. Build it with :meth:`from_env` or directly."""

    provider: Provider = "ollama"
    model: str = DEFAULT_OLLAMA_MODEL
    ollama_host: str = DEFAULT_OLLAMA_HOST
    allow_remote_ollama: bool = False
    temperature: float = 0.0
    max_iterations: int = 3
    approval_threshold: int = 8
    max_request_tokens: int = 6000
    max_run_tokens: int = 60000
    support_threshold: float = 0.6
    target_words: tuple[int, int] = (120, 900)
    sources_dir: Path = field(default=BUNDLED_SOURCES)

    def __post_init__(self) -> None:
        if self.provider not in PROVIDERS:
            raise ConfigError(f"provider must be one of {', '.join(PROVIDERS)}")
        remote = not is_loopback(self.ollama_host)
        if self.provider == "ollama" and remote and not self.allow_remote_ollama:
            raise ConfigError(
                f"OLLAMA_HOST {self.ollama_host!r} is not loopback; set "
                "DESK_ALLOW_REMOTE_OLLAMA=1 to send prompts to another machine"
            )
        if not 1 <= self.max_iterations <= 10:
            raise ConfigError("max_iterations must be between 1 and 10")
        if not 0 <= self.approval_threshold <= 10:
            raise ConfigError("approval_threshold must be between 0 and 10")

    @classmethod
    def from_env(cls, env: Mapping[str, str] | None = None) -> Settings:
        """Read ``DESK_*`` variables (and ``OLLAMA_HOST``) from ``env`` or ``os.environ``."""
        env = os.environ if env is None else env
        provider = env.get("DESK_PROVIDER", "ollama").strip().lower() or "ollama"
        if provider not in PROVIDERS:
            raise ConfigError(f"DESK_PROVIDER must be one of {', '.join(PROVIDERS)}")
        default_model = DEFAULT_GEMINI_MODEL if provider == "gemini" else DEFAULT_OLLAMA_MODEL
        sources = env.get("DESK_SOURCES", "").strip()
        return cls(
            provider=provider,
            model=env.get("DESK_MODEL", "").strip() or default_model,
            ollama_host=env.get("OLLAMA_HOST", "").strip() or DEFAULT_OLLAMA_HOST,
            allow_remote_ollama=env.get("DESK_ALLOW_REMOTE_OLLAMA", "") == "1",
            temperature=_float(env, "DESK_TEMPERATURE", 0.0, 0.0, 2.0),
            max_iterations=_int(env, "DESK_MAX_ITERATIONS", 3, 1, 10),
            approval_threshold=_int(env, "DESK_APPROVAL_THRESHOLD", 8, 0, 10),
            max_request_tokens=_int(env, "DESK_MAX_REQUEST_TOKENS", 6000, 256, 1_000_000),
            max_run_tokens=_int(env, "DESK_MAX_RUN_TOKENS", 60000, 1024, 10_000_000),
            support_threshold=_float(env, "DESK_SUPPORT_THRESHOLD", 0.6, 0.0, 1.0),
            sources_dir=Path(sources).expanduser() if sources else BUNDLED_SOURCES,
        )
