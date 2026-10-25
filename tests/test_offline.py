"""The whole desk on OfflineDeskModel: the default demo, eval and CI path."""

from __future__ import annotations

import re
from dataclasses import replace

import pytest

from content_desk import run_desk
from content_desk.config import BUNDLED_SOURCES
from content_desk.offline import NO_SOURCES
from content_desk.offline import OfflineDeskModel
from content_desk.offline import block
from content_desk.offline import planted_claim
from content_desk.pipeline import build_pipeline
from content_desk.schemas import FactCheckReport
from content_desk.sources import SourcePack


async def test_offline_desk_writes_a_reviewed_cited_post(settings) -> None:
    result = await run_desk("SQLite write-ahead logging", settings)
    state = result.state
    assert [h["score"] for h in state["review_history"]] == [6, 9]
    assert state["review"]["approved"] is True

    report = FactCheckReport.model_validate(state["fact_check"])
    unsupported = [c.claim for c in report.claims if c.verdict == "unsupported"]
    assert unsupported == [planted_claim("SQLite write-ahead logging")]
    assert report.unsupported_count == 1
    assert len(report.claims) > 5

    post = result.final_post
    assert post.startswith("# A practical guide to SQLite write-ahead logging")
    assert planted_claim("SQLite write-ahead logging") not in post, "the editor removed it"
    assert planted_claim("SQLite write-ahead logging") in state["draft"]
    cited = set(re.findall(r"\[([a-z0-9-]+)\]", post))
    assert cited and cited <= set(SourcePack.load(BUNDLED_SOURCES).ids)
    assert "## Sources" in post


async def test_the_planted_claim_is_the_only_one_flagged_across_topics(settings) -> None:
    for topic in ("WAL checkpoints", "concurrency in WAL mode", "WAL on network filesystems"):
        result = await run_desk(topic, settings)
        report = FactCheckReport.model_validate(result.state["fact_check"])
        assert report.unsupported_count == 1, topic


async def test_a_topic_the_pack_does_not_cover_still_finishes(settings) -> None:
    result = await run_desk("Kubernetes helm charts", settings)
    assert result.state["research_notes"] == NO_SOURCES
    assert result.state["outline"]["sections"][0]["heading"] == "What the sources cover"
    assert result.final_post.startswith("# A practical guide to Kubernetes helm charts")


async def test_strict_threshold_runs_every_round(settings) -> None:
    root = build_pipeline(replace(settings, approval_threshold=10, max_iterations=2))
    result = await run_desk("SQLite WAL", root=root)
    assert [h["approved"] for h in result.state["review_history"]] == [False, False]


def test_unknown_role_is_an_error() -> None:
    from google.adk.models.llm_request import LlmRequest

    with pytest.raises(ValueError, match="no role"):
        OfflineDeskModel(model="offline/x", role="poet").reply(LlmRequest())


def test_block() -> None:
    assert block("a <x> b </x>", "x") == "b"
    assert block("no tags", "x") == ""
    assert block("</x> <x>", "x") == ""
