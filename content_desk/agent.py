"""ADK entry point: ``root_agent`` for ``adk web``, ``adk run`` and ``adk eval``.

The provider comes from ``DESK_PROVIDER`` (``ollama`` by default, ``stub`` offline,
``gemini`` with your own key); see :class:`content_desk.config.Settings`.
"""

from __future__ import annotations

from content_desk.config import Settings
from content_desk.pipeline import build_pipeline

root_agent = build_pipeline(Settings.from_env())
