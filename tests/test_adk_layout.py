"""``content_desk`` is an ADK agent folder: ``agent.root_agent`` for adk web/run/eval."""

from __future__ import annotations

import importlib

import pytest
from google.adk.agents import SequentialAgent

import content_desk


def test_root_agent_is_built_from_the_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("DESK_PROVIDER", "stub")
    module = importlib.reload(importlib.import_module("content_desk.agent"))
    assert isinstance(module.root_agent, SequentialAgent)
    assert module.root_agent.name == "content_desk"
    assert content_desk.agent is module  # the lazy attribute ADK's loaders look for
    assert content_desk.__version__ == "0.1.0"


def test_unknown_attribute() -> None:
    with pytest.raises(AttributeError):
        content_desk.nope  # noqa: B018
