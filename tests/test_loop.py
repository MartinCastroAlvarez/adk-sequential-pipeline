"""The LoopAgent: it ends on the critic's exit_loop, or at max_iterations."""

from __future__ import annotations

import pytest

from content_desk import run_desk
from content_desk.stub import ToolCall
from tests.conftest import APPROVE
from tests.conftest import REJECT
from tests.conftest import review


async def test_loop_exits_on_first_approval(scripted) -> None:
    desk = scripted(critic=[APPROVE], writer=["# T\n\nonly draft"])
    result = await run_desk("SQLite WAL", root=desk.root)
    assert desk.models["writer"].calls == 1
    assert desk.models["critic"].calls == 1
    assert result.state["review_history"] == [{"score": 9, "approved": True}]
    escalations = [e.author for e in result.events if e.actions.escalate]
    assert escalations == ["critic"]
    assert desk.models["fact_checker"].calls == 2, "the pipeline continues after the loop"


@pytest.mark.parametrize("rounds", [1, 2, 3, 5])
async def test_loop_stops_at_max_iterations_without_approval(scripted, rounds: int) -> None:
    desk = scripted(
        settings_changes={"max_iterations": rounds},
        critic=[REJECT],
        writer=["# T\n\nanother draft"],
        repeat=("critic", "writer"),
    )
    result = await run_desk("SQLite WAL", root=desk.root)
    assert desk.models["writer"].calls == rounds
    assert desk.models["critic"].calls == rounds
    assert [h["approved"] for h in result.state["review_history"]] == [False] * rounds
    assert not any(e.actions.escalate for e in result.events)
    assert result.state["review"]["approved"] is False
    assert desk.models["editor"].calls == 1, "a rejected draft still reaches the editor"


async def test_exit_loop_next_to_a_failing_score_is_dropped(scripted) -> None:
    sneaky = [ToolCall("set_model_response", review(5, False)), ToolCall("exit_loop")]
    desk = scripted(critic=[sneaky, APPROVE])
    result = await run_desk("SQLite WAL", root=desk.root)
    assert desk.models["writer"].calls == 2, "the guard kept the loop going"
    assert [h["score"] for h in result.state["review_history"]] == [5, 9]
    blocked = [e for e in result.guardrail_events if e["kind"] == "exit_blocked"]
    assert blocked == [
        {
            "agent": "critic",
            "kind": "exit_blocked",
            "detail": "exit_loop with score 5 (threshold 8, approved=False)",
        }
    ]


async def test_exit_loop_claiming_approval_below_threshold_is_dropped(scripted) -> None:
    liar = [ToolCall("set_model_response", review(7, True)), ToolCall("exit_loop")]
    desk = scripted(critic=[liar, APPROVE])
    await run_desk("SQLite WAL", root=desk.root)
    assert desk.models["writer"].calls == 2


async def test_exit_loop_without_a_verdict_is_dropped(scripted) -> None:
    desk = scripted(
        critic=[ToolCall("exit_loop"), REJECT, APPROVE],
        writer=["# T\n\ndraft"],
        repeat=("writer",),
    )
    result = await run_desk("SQLite WAL", root=desk.root)
    kinds = [e["detail"] for e in result.guardrail_events if e["kind"] == "exit_blocked"]
    assert kinds == ["exit_loop without a verdict in the same turn"]
    # Round 1 ends with no verdict at all, round 2 rejects, round 3 approves.
    assert desk.models["writer"].calls == 3
    assert [h["score"] for h in result.state["review_history"]] == [4, 9]


async def test_threshold_is_configurable(scripted) -> None:
    passing_at_5 = [ToolCall("set_model_response", review(5, True)), ToolCall("exit_loop")]
    desk = scripted(settings_changes={"approval_threshold": 5}, critic=[passing_at_5])
    await run_desk("SQLite WAL", root=desk.root)
    assert desk.models["writer"].calls == 1
    critic_prompt = desk.models["critic"].requests[0].config.system_instruction
    assert "at\nleast 5" in critic_prompt or "at least 5" in critic_prompt
