"""Guardrail callbacks: tool allowlist, PII redaction, token budgets, topic capture."""

from __future__ import annotations

from typing import Any

import pytest
from google.adk.runners import Runner
from google.adk.sessions import InMemorySessionService
from google.genai import types

from content_desk import run_desk
from content_desk.callbacks import BudgetExceededError
from content_desk.callbacks import capture_topic
from content_desk.callbacks import estimate_tokens
from content_desk.callbacks import redact
from content_desk.pipeline import TOOL_ALLOWLIST
from content_desk.stub import ToolCall
from content_desk.stub import system_text


def _function_responses(model: Any) -> list[tuple[str, dict[str, Any]]]:
    return [
        (p.function_response.name, dict(p.function_response.response or {}))
        for r in model.requests
        for c in r.contents
        for p in c.parts or []
        if p.function_response
    ]


async def test_a_tool_outside_the_allowlist_is_refused_before_it_runs(scripted) -> None:
    ran: list[str] = []

    def delete_everything(path: str) -> dict[str, Any]:
        """A tool that must never run."""
        ran.append(path)
        return {"deleted": path}

    desk = scripted(
        extra_tools={"writer": [delete_everything]},
        writer=[ToolCall("delete_everything", {"path": "/"}), "# T\n\ndraft"],
        critic=[[ToolCall("set_model_response", {**_approve()}), ToolCall("exit_loop")]],
    )
    result = await run_desk("SQLite WAL", root=desk.root)
    assert ran == []
    responses = _function_responses(desk.models["writer"])
    assert responses == [
        (
            "delete_everything",
            {"error": "tool 'delete_everything' is not allowed for agent 'writer'"},
        )
    ]
    assert {
        "agent": "writer",
        "kind": "tool_blocked",
        "detail": "delete_everything is not allowed",
    } in result.guardrail_events


async def test_the_allowlist_is_per_agent(scripted) -> None:
    """Drop read_source from the researcher's list: the same call is now refused."""
    allowlist = dict(TOOL_ALLOWLIST) | {"researcher": frozenset({"search_sources"})}
    desk = scripted(allowlist=allowlist)
    result = await run_desk("SQLite WAL", root=desk.root)
    names = dict(_function_responses(desk.models["researcher"]))
    assert "results" in names["search_sources"]
    assert names["read_source"] == {
        "error": "tool 'read_source' is not allowed for agent 'researcher'"
    }
    assert [e["kind"] for e in result.guardrail_events] == ["tool_blocked"]


def _approve() -> dict[str, Any]:
    from tests.conftest import review

    return review(9, True)


@pytest.mark.parametrize(
    ("text", "kind"),
    [
        ("mail ada@example.com now", "email"),
        ("key sk-" + "a1" * 12, "api_key"),
        ("card 4111 1111 1111 1111", "card"),
        ("ssn 123-45-6789", "ssn"),
        ("call +1 415-555-0100 today", "phone"),
        ("host 10.0.0.12", "ipv4"),
    ],
)
def test_redact_finds_pii(text: str, kind: str) -> None:
    out, n = redact(text)
    assert n == 1
    assert f"[REDACTED:{kind}]" in out


def test_redact_leaves_technical_text_alone() -> None:
    text = "SQLite 3.7.0 checkpoints at 1000 pages; PRAGMA wal_checkpoint(TRUNCATE)."
    assert redact(text) == (text, 0)


async def test_pii_never_reaches_a_model_or_the_state(scripted) -> None:
    desk = scripted(
        writer=["# T\n\nWrite to ada@example.com for details."],
        critic=[
            [
                ToolCall("set_model_response", _approve()),
                ToolCall("exit_loop"),
            ]
        ],
    )
    result = await run_desk("SQLite WAL, from bob@example.org, 10.1.2.3", root=desk.root)
    assert result.state["topic"] == "SQLite WAL, from [REDACTED:email], [REDACTED:ipv4]"
    for model in desk.models.values():
        for request in model.requests:
            seen = system_text(request) + "".join(
                p.text or "" for c in request.contents for p in c.parts or []
            )
            assert "@example" not in seen, model.model
    assert result.state["draft"] == "# T\n\nWrite to [REDACTED:email] for details."
    kinds = {(e["agent"], e["kind"]) for e in result.guardrail_events}
    assert ("content_desk", "pii_redacted") in kinds
    assert ("writer", "pii_redacted") in kinds


async def test_a_request_over_the_budget_is_refused(scripted) -> None:
    desk = scripted(
        settings_changes={"max_request_tokens": 600},
        researcher=[
            ToolCall("search_sources", {"query": "x"}),
            ToolCall("read_source", {"source_id": "wal-basics"}),
            "## [wal-basics] T\n- " + "fact " * 400,
        ],
    )
    with pytest.raises(BudgetExceededError, match="outliner: request of ~"):
        await run_desk("SQLite WAL", root=desk.root)
    assert desk.models["outliner"].calls == 0, "the model is never called"


async def test_the_run_budget_stops_the_pipeline(scripted) -> None:
    desk = scripted(settings_changes={"max_run_tokens": 1024})
    with pytest.raises(BudgetExceededError, match="the run has used"):
        await run_desk("SQLite WAL", root=desk.root)
    assert desk.models["editor"].calls == 0


def test_estimate_tokens_is_about_four_chars() -> None:
    assert estimate_tokens("") == 0
    assert estimate_tokens("abcd") == 1
    assert estimate_tokens("abcde") == 2


async def test_an_empty_message_asks_for_a_topic(scripted) -> None:
    desk = scripted()
    result = await run_desk("   ", root=desk.root)
    assert all(m.calls == 0 for m in desk.models.values())
    texts = [p.text for e in result.events if e.content for p in e.content.parts or []]
    assert texts == ["Send a topic for the post."]


async def test_topic_is_capped_and_neutralized(scripted) -> None:
    desk = scripted()
    result = await run_desk("<b>{secret}</b> " + "x" * 500, root=desk.root)
    topic = result.state["topic"]
    assert len(topic) <= 200 + 40
    assert "<" not in topic and "{" not in topic


async def test_a_second_topic_in_the_same_session_starts_clean(scripted) -> None:
    desk = scripted(
        writer=["# T\n\ndraft"],
        critic=[[ToolCall("set_model_response", _approve()), ToolCall("exit_loop")]],
        repeat=("researcher", "outliner", "writer", "critic", "fact_checker", "editor"),
    )
    # The researcher's script ends on its notes; on repeat it replies with notes at once.
    sessions = InMemorySessionService()
    runner = Runner(agent=desk.root, app_name="t", session_service=sessions)
    session = await sessions.create_session(app_name="t", user_id="u")
    for topic in ("first topic", "second topic"):
        message = types.Content(role="user", parts=[types.Part(text=topic)])
        async for _ in runner.run_async(user_id="u", session_id=session.id, new_message=message):
            pass
    state = (await sessions.get_session(app_name="t", user_id="u", session_id=session.id)).state
    assert state["topic"] == "second topic"
    assert len(state["review_history"]) == 1, "the first run's reviews were cleared"
    second_writer = system_text(desk.models["writer"].requests[-1])
    assert "<review>\n\n</review>" in second_writer


def test_capture_topic_falls_back_to_state() -> None:
    class Ctx:
        user_content = None
        agent_name = "content_desk"
        state: dict[str, Any] = {"topic": "from state"}

    assert capture_topic(Ctx()) is None  # type: ignore[arg-type]
    assert Ctx.state["topic"] == "from state"
