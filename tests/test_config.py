"""Settings from the environment and the model each provider gets."""

from __future__ import annotations

from pathlib import Path

import pytest
from google.adk.models.lite_llm import LiteLlm

from content_desk.config import BUNDLED_SOURCES
from content_desk.config import ConfigError
from content_desk.config import Settings
from content_desk.config import is_loopback
from content_desk.models import default_models
from content_desk.models import ollama_model_id
from content_desk.offline import OfflineDeskModel


def test_defaults_are_local() -> None:
    s = Settings.from_env({})
    assert (s.provider, s.model, s.ollama_host) == ("ollama", "qwen3:4b", "http://127.0.0.1:11434")
    assert (s.max_iterations, s.approval_threshold) == (3, 8)
    assert s.sources_dir == BUNDLED_SOURCES


def test_env_overrides(tmp_path: Path) -> None:
    s = Settings.from_env(
        {
            "DESK_PROVIDER": "Gemini",
            "DESK_MAX_ITERATIONS": "5",
            "DESK_APPROVAL_THRESHOLD": "7",
            "DESK_TEMPERATURE": "0.3",
            "DESK_SUPPORT_THRESHOLD": "0.5",
            "DESK_MAX_REQUEST_TOKENS": "4000",
            "DESK_MAX_RUN_TOKENS": "40000",
            "DESK_SOURCES": str(tmp_path),
        }
    )
    assert s.provider == "gemini" and s.model == "gemini-3.5-flash"
    assert (s.max_iterations, s.approval_threshold, s.temperature) == (5, 7, 0.3)
    assert (s.support_threshold, s.max_request_tokens, s.max_run_tokens) == (0.5, 4000, 40000)
    assert s.sources_dir == tmp_path


@pytest.mark.parametrize(
    "env",
    [
        {"DESK_PROVIDER": "openai"},
        {"DESK_MAX_ITERATIONS": "0"},
        {"DESK_MAX_ITERATIONS": "many"},
        {"DESK_APPROVAL_THRESHOLD": "11"},
        {"DESK_TEMPERATURE": "hot"},
        {"DESK_TEMPERATURE": "9"},
        {"OLLAMA_HOST": "http://10.0.0.5:11434"},
    ],
)
def test_bad_env_is_refused(env: dict[str, str]) -> None:
    with pytest.raises(ConfigError):
        Settings.from_env(env)


def test_direct_construction_is_validated_too() -> None:
    with pytest.raises(ConfigError):
        Settings(provider="openai")  # type: ignore[arg-type]
    with pytest.raises(ConfigError):
        Settings(max_iterations=20)
    with pytest.raises(ConfigError):
        Settings(approval_threshold=-1)


def test_remote_ollama_needs_an_explicit_opt_in() -> None:
    s = Settings.from_env({"OLLAMA_HOST": "http://gpu-box:11434", "DESK_ALLOW_REMOTE_OLLAMA": "1"})
    assert s.ollama_host == "http://gpu-box:11434"


@pytest.mark.parametrize(
    ("url", "loopback"),
    [
        ("http://127.0.0.1:11434", True),
        ("http://localhost:11434", True),
        ("http://[::1]:11434", True),
        ("http://127.8.0.1", True),
        ("http://10.0.0.1", False),
        ("http://example.com", False),
        ("not a url", False),
    ],
)
def test_is_loopback(url: str, loopback: bool) -> None:
    assert is_loopback(url) is loopback


def test_ollama_gets_one_litellm_wrapper() -> None:
    factory = default_models(Settings.from_env({}))
    model = factory("writer")
    assert isinstance(model, LiteLlm)
    assert model.model == "ollama_chat/qwen3:4b"
    assert factory("critic") is model
    assert ollama_model_id("ollama/llama3.2") == "ollama/llama3.2"


def test_gemini_needs_a_key_and_is_a_model_id() -> None:
    settings = Settings.from_env({"DESK_PROVIDER": "gemini"})
    with pytest.raises(ConfigError, match="GOOGLE_API_KEY"):
        default_models(settings, env={})
    factory = default_models(settings, env={"GOOGLE_API_KEY": "test-not-a-key"})
    assert factory("writer") == "gemini-3.5-flash"


def test_stub_gets_one_offline_model_per_role() -> None:
    factory = default_models(Settings.from_env({"DESK_PROVIDER": "stub"}))
    writer = factory("writer")
    assert isinstance(writer, OfflineDeskModel) and writer.role == "writer"
    assert writer.capabilities.output_schema_and_tools is False
