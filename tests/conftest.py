"""Shared fixtures: a stub-provider Settings and a fully scripted desk."""

from __future__ import annotations

from dataclasses import dataclass
from dataclasses import replace
from typing import Any

import pytest

from content_desk.config import Settings
from content_desk.pipeline import build_pipeline
from content_desk.schemas import ClaimCheck
from content_desk.schemas import FactCheckReport
from content_desk.schemas import Outline
from content_desk.schemas import Review
from content_desk.schemas import Rubric
from content_desk.schemas import Section
from content_desk.stub import Reply
from content_desk.stub import ScriptedLlm
from content_desk.stub import ToolCall

NOTES = "## [wal-basics] SQLite write-ahead logging, the basics\n- WAL appends changed pages to a -wal file."
OUTLINE = Outline(
    title="WAL in one page",
    sections=[
        Section(heading="How WAL works", key_points=["Appends pages"], source_ids=["wal-basics"])
    ],
)


def review(score: int, approved: bool, issues: list[str] | None = None) -> dict[str, Any]:
    return Review(
        score=score,
        rubric=Rubric(coverage=3, citations=max(0, min(4, score - 4)), structure=1, length=0),
        issues=issues or [],
        approved=approved,
    ).model_dump()


REJECT = [ToolCall("set_model_response", review(4, False, ["Cite every sentence."]))]
APPROVE = [ToolCall("set_model_response", review(9, True)), ToolCall("exit_loop")]
SUPPORTED = "In write-ahead logging mode, SQLite leaves the database file alone during a write."
UNSUPPORTED = "WAL mode makes SQLite faster than every other database."
REPORT = FactCheckReport(
    claims=[
        ClaimCheck(claim=SUPPORTED, verdict="supported", source_id="wal-basics", evidence="..."),
        ClaimCheck(claim=UNSUPPORTED, verdict="unsupported"),
    ],
    unsupported_count=1,
).model_dump()


def default_scripts() -> dict[str, list[Reply]]:
    return {
        "researcher": [
            ToolCall("search_sources", {"query": "SQLite WAL"}),
            ToolCall("read_source", {"source_id": "wal-basics"}),
            NOTES,
        ],
        "outliner": [OUTLINE],
        "writer": ["# WAL in one page\n\ndraft v1", "# WAL in one page\n\ndraft v2"],
        "critic": [REJECT, APPROVE],
        "fact_checker": [
            [
                ToolCall("check_claim", {"claim": SUPPORTED}),
                ToolCall("check_claim", {"claim": UNSUPPORTED}),
            ],
            ToolCall("set_model_response", REPORT),
        ],
        "editor": ["# WAL in one page\n\nfinal post [wal-basics]"],
    }


@dataclass
class Desk:
    root: Any
    models: dict[str, ScriptedLlm]
    settings: Settings


@pytest.fixture
def settings() -> Settings:
    return replace(Settings(), provider="stub")


@pytest.fixture
def scripted(settings: Settings) -> Any:
    """``scripted(critic=[...], max_iterations=2)`` -> a Desk with one ScriptedLlm per agent."""

    def make(
        settings_changes: dict[str, Any] | None = None,
        extra_tools: dict[str, list[Any]] | None = None,
        allowlist: Any = None,
        repeat: tuple[str, ...] = (),
        **scripts: list[Reply],
    ) -> Desk:
        merged = default_scripts() | scripts
        models = {
            name: ScriptedLlm(model=f"scripted/{name}", script=script, repeat_last=name in repeat)
            for name, script in merged.items()
        }
        s = replace(settings, **(settings_changes or {}))
        kwargs: dict[str, Any] = {"extra_tools": extra_tools}
        if allowlist is not None:
            kwargs["allowlist"] = allowlist
        return Desk(build_pipeline(s, models=models, **kwargs), models, s)

    return make
