"""Which model each agent gets.

* ``ollama`` (default): ``LiteLlm(model="ollama_chat/<model>")`` on a loopback ollama.
* ``gemini`` (optional): the Gemini model id as a string; ADK resolves it and reads
  ``GOOGLE_API_KEY`` (or Vertex settings) itself. Never used by tests or CI.
* ``stub``: :class:`content_desk.offline.OfflineDeskModel`, deterministic and offline.

A ``ModelFactory`` maps an agent name to a model, so tests can script every agent.
"""

from __future__ import annotations

import os
from collections.abc import Callable
from collections.abc import Mapping

from google.adk.models.base_llm import BaseLlm

from content_desk.config import ConfigError
from content_desk.config import Settings

ModelFactory = Callable[[str], BaseLlm | str]


def ollama_model_id(model: str) -> str:
    """``qwen3:4b`` -> ``ollama_chat/qwen3:4b`` (the provider LiteLLM uses for tools)."""
    return model if model.startswith(("ollama_chat/", "ollama/")) else f"ollama_chat/{model}"


def default_models(settings: Settings, env: Mapping[str, str] | None = None) -> ModelFactory:
    """The model factory for ``settings.provider``."""
    env = os.environ if env is None else env
    if settings.provider == "stub":
        from content_desk.offline import OfflineDeskModel

        def offline(role: str) -> BaseLlm:
            return OfflineDeskModel(
                model=f"offline/{role}",
                role=role,
                threshold=settings.approval_threshold,
                support_threshold=settings.support_threshold,
                target_words=settings.target_words,
            )

        return offline

    if settings.provider == "gemini":
        has_key = env.get("GOOGLE_API_KEY") or env.get("GOOGLE_GENAI_USE_VERTEXAI") == "1"
        if not has_key:
            raise ConfigError(
                "DESK_PROVIDER=gemini needs GOOGLE_API_KEY (or Vertex AI settings); "
                "the default provider is a local ollama"
            )
        model_id = settings.model
        return lambda role: model_id

    from google.adk.models.lite_llm import LiteLlm

    shared = LiteLlm(model=ollama_model_id(settings.model), api_base=settings.ollama_host)
    return lambda role: shared
