"""ADK's own evaluator (``AgentEvaluator``, what ``adk eval`` runs) on the stub desk."""

from __future__ import annotations

import importlib
import json
from pathlib import Path

import pytest
from google.adk.evaluation.agent_evaluator import AgentEvaluator
from google.adk.evaluation.eval_set import EvalSet

EVALS = Path(__file__).resolve().parent.parent / "evals"


@pytest.fixture
def stub_agent(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("DESK_PROVIDER", "stub")
    importlib.reload(importlib.import_module("content_desk.agent"))


def _eval_set() -> EvalSet:
    return EvalSet.model_validate_json((EVALS / "content_desk.evalset.json").read_text())


async def test_eval_set_passes(stub_agent: None) -> None:
    config = AgentEvaluator.find_config_for_test_file(str(EVALS / "content_desk.evalset.json"))
    assert set(config.criteria) == {"tool_trajectory_avg_score", "response_match_score"}
    await AgentEvaluator.evaluate_eval_set(
        agent_module="content_desk.agent",
        eval_set=_eval_set(),
        eval_config=config,
        num_runs=1,
        print_detailed_results=False,
    )


async def test_eval_catches_a_wrong_trajectory(stub_agent: None) -> None:
    eval_set = _eval_set()
    case = eval_set.eval_cases[0]
    uses = case.conversation[0].intermediate_data.tool_uses  # type: ignore[union-attr, index]
    uses[1].args = {"source_id": "wal-limitations"}
    config = AgentEvaluator.find_config_for_test_file(str(EVALS / "content_desk.evalset.json"))
    with pytest.raises(AssertionError, match="tool_trajectory_avg_score"):
        await AgentEvaluator.evaluate_eval_set(
            agent_module="content_desk.agent",
            eval_set=eval_set,
            eval_config=config,
            num_runs=1,
            print_detailed_results=False,
        )


def test_eval_set_is_recorded_from_the_stub() -> None:
    data = json.loads((EVALS / "content_desk.evalset.json").read_text())
    names = [
        u["name"]
        for c in data["eval_cases"]
        for u in c["conversation"][0]["intermediate_data"]["tool_uses"]
    ]
    assert names.count("exit_loop") == len(data["eval_cases"])
