"""content_desk: a Google ADK SequentialAgent with a writer/critic LoopAgent inside.

``import content_desk`` does not build an agent; ADK's loaders import
``content_desk.agent`` (which builds ``root_agent`` from the environment). The
``agent`` attribute is resolved lazily so ``adk eval`` and ``AgentEvaluator`` find it.
"""

from __future__ import annotations

import importlib
from typing import Any

from content_desk.config import Settings
from content_desk.pipeline import TOOL_ALLOWLIST
from content_desk.pipeline import build_pipeline
from content_desk.runner import DeskResult
from content_desk.runner import run_desk

__all__ = ["TOOL_ALLOWLIST", "DeskResult", "Settings", "build_pipeline", "run_desk"]
__version__ = "0.1.0"


def __getattr__(name: str) -> Any:
    if name == "agent":
        return importlib.import_module("content_desk.agent")
    raise AttributeError(f"module 'content_desk' has no attribute {name!r}")
