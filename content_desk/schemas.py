"""Structured outputs: what the outliner, critic and fact-checker must return.

ADK validates each agent's final answer against its ``output_schema`` and stores the
parsed dict under its ``output_key``. The ``*_text`` views in :mod:`content_desk.views`
turn them into the text that later instructions template in.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel
from pydantic import ConfigDict
from pydantic import Field

SOURCE_ID_PATTERN = r"^[a-z0-9][a-z0-9-]{0,63}$"


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


class Section(_Strict):
    heading: str = Field(min_length=1, max_length=120)
    key_points: list[str] = Field(min_length=1, max_length=8)
    source_ids: list[str] = Field(default_factory=list, max_length=8)


class Outline(_Strict):
    """The outliner's plan: a title and 2-6 sections, each tied to sources."""

    title: str = Field(min_length=1, max_length=160)
    sections: list[Section] = Field(min_length=1, max_length=6)


class Rubric(_Strict):
    coverage: int = Field(ge=0, le=3, description="every outline section is covered")
    citations: int = Field(ge=0, le=4, description="factual sentences cite a [source-id]")
    structure: int = Field(ge=0, le=1, description="a title and an introduction")
    length: int = Field(ge=0, le=2, description="within the target word range")


class Review(_Strict):
    """The critic's verdict. ``score`` is the rubric total, out of 10."""

    score: int = Field(ge=0, le=10)
    rubric: Rubric
    issues: list[str] = Field(default_factory=list, max_length=10)
    approved: bool


class ClaimCheck(_Strict):
    claim: str = Field(min_length=1, max_length=600)
    verdict: Literal["supported", "unsupported"]
    source_id: str | None = None
    evidence: str = Field(default="", max_length=600)


class FactCheckReport(_Strict):
    """One entry per factual sentence of the draft."""

    claims: list[ClaimCheck] = Field(default_factory=list, max_length=60)
    unsupported_count: int = Field(ge=0)
