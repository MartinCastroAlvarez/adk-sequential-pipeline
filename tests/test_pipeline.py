"""The agent tree, the run order and the state handoff."""

from __future__ import annotations

from google.adk.agents import LlmAgent
from google.adk.agents import LoopAgent
from google.adk.agents import SequentialAgent

from content_desk import run_desk
from content_desk.pipeline import AGENTS
from content_desk.pipeline import OUTPUT_KEYS
from content_desk.pipeline import TOOL_ALLOWLIST
from content_desk.pipeline import build_pipeline
from content_desk.pipeline import walk
from content_desk.schemas import FactCheckReport
from content_desk.schemas import Outline
from content_desk.schemas import Review
from content_desk.stub import system_text
from tests.conftest import NOTES
from tests.conftest import UNSUPPORTED


def test_tree_is_a_sequence_with_a_writer_critic_loop(settings) -> None:
    root = build_pipeline(settings)
    assert isinstance(root, SequentialAgent)
    assert [a.name for a in root.sub_agents] == [
        "researcher",
        "outliner",
        "revision_loop",
        "fact_checker",
        "editor",
    ]
    loop = root.sub_agents[2]
    assert isinstance(loop, LoopAgent)
    assert loop.max_iterations == settings.max_iterations
    assert [a.name for a in loop.sub_agents] == ["writer", "critic"]
    llm_agents = [a for a in walk(root) if isinstance(a, LlmAgent)]
    assert [a.name for a in llm_agents] == list(AGENTS)
    for agent in llm_agents:
        assert agent.output_key == OUTPUT_KEYS[agent.name]
        tool_names = {getattr(t, "name", getattr(t, "__name__", "")) for t in agent.tools}
        assert tool_names <= TOOL_ALLOWLIST[agent.name], agent.name
        if agent.name != "researcher":
            assert agent.include_contents == "none", "downstream agents read state, not chat"


def test_structured_agents_have_schemas(settings) -> None:
    agents = {a.name: a for a in walk(build_pipeline(settings))}
    assert agents["outliner"].output_schema is Outline
    assert agents["critic"].output_schema is Review
    assert agents["fact_checker"].output_schema is FactCheckReport


async def test_agents_run_in_pipeline_order(scripted) -> None:
    desk = scripted()
    result = await run_desk("SQLite WAL", root=desk.root)
    assert [a for a in result.authors if a != "content_desk"] == [
        "researcher",
        "outliner",
        "writer",
        "critic",
        "writer",
        "critic",
        "fact_checker",
        "editor",
    ]
    assert {name: m.calls for name, m in desk.models.items()} == {
        "researcher": 3,
        "outliner": 1,
        "writer": 2,
        "critic": 2,
        "fact_checker": 2,
        "editor": 1,
    }


async def test_every_output_key_lands_in_state(scripted) -> None:
    result = await run_desk("SQLite WAL", root=scripted().root)
    state = result.state
    assert state["topic"] == "SQLite WAL"
    assert state["research_notes"] == NOTES
    assert Outline.model_validate(state["outline"]).title == "WAL in one page"
    assert state["draft"].endswith("draft v2")
    assert Review.model_validate(state["review"]).approved is True
    assert state["review_history"] == [
        {"score": 4, "approved": False},
        {"score": 9, "approved": True},
    ]
    assert FactCheckReport.model_validate(state["fact_check"]).unsupported_count == 1
    assert (
        result.final_post == state["final_post"] == "# WAL in one page\n\nfinal post [wal-basics]"
    )
    assert state["outline_text"].startswith(
        "# WAL in one page\n## How WAL works (sources: wal-basics)"
    )
    assert "Not approved" not in state["review_text"]


async def test_placeholders_carry_state_between_agents(scripted) -> None:
    desk = scripted()
    await run_desk("SQLite WAL", root=desk.root)
    researcher = system_text(desk.models["researcher"].requests[0])
    assert "<topic>SQLite WAL</topic>" in researcher

    first, second = (system_text(r) for r in desk.models["writer"].requests)
    assert "## How WAL works (sources: wal-basics)" in first  # {outline_text}
    assert "WAL appends changed pages" in first  # {research_notes}
    assert "<review>\n\n</review>" in first  # {review_text?} is optional and empty
    assert "Score 4/10" in second and "Cite every sentence." in second

    critic_1, critic_2 = (system_text(r) for r in desk.models["critic"].requests)
    assert "draft v1" in critic_1 and "draft v2" in critic_2

    editor = system_text(desk.models["editor"].requests[0])
    assert "draft v2" in editor
    assert f"- {UNSUPPORTED}" in editor  # {fact_check_text}


async def test_state_only_agents_never_see_the_researchers_tool_calls(scripted) -> None:
    desk = scripted()
    await run_desk("SQLite WAL", root=desk.root)
    for request in desk.models["writer"].requests:
        names = [
            p.function_response.name
            for c in request.contents
            for p in c.parts or []
            if p.function_response
        ]
        assert names == []


async def test_set_model_response_is_offered_to_tool_using_schema_agents(scripted) -> None:
    desk = scripted()
    await run_desk("SQLite WAL", root=desk.root)
    critic_tools = set(desk.models["critic"].requests[0].tools_dict)
    assert critic_tools == {"exit_loop", "set_model_response"}
    assert set(desk.models["fact_checker"].requests[0].tools_dict) == {
        "check_claim",
        "set_model_response",
    }
    assert desk.models["outliner"].requests[0].tools_dict == {}
