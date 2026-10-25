"""Text views of structured state, for the next agent's ``{placeholder}``.

``output_schema`` agents store a dict under their ``output_key``. Templating a dict
into an instruction would paste its Python repr, so each structured agent gets an
``after_agent_callback`` that also writes a short Markdown view (``outline_text``,
``review_text``, ``fact_check_text``). Code reads the dicts; prompts read the views.
"""

from __future__ import annotations

from typing import Any

from google.adk.agents.callback_context import CallbackContext
from google.genai import types

from content_desk.schemas import FactCheckReport
from content_desk.schemas import Outline
from content_desk.schemas import Review

REVIEW_HISTORY_KEY = "review_history"


def outline_text(outline: Outline) -> str:
    lines = [f"# {outline.title}"]
    for section in outline.sections:
        ids = ", ".join(section.source_ids)
        lines.append(f"## {section.heading}" + (f" (sources: {ids})" if ids else ""))
        lines.extend(f"- {point}" for point in section.key_points)
    return "\n".join(lines)


def review_text(review: Review) -> str:
    r = review.rubric
    head = (
        f"Score {review.score}/10 (coverage {r.coverage}/3, citations {r.citations}/4, "
        f"structure {r.structure}/1, length {r.length}/2). "
        + ("Approved." if review.approved else "Not approved.")
    )
    if not review.issues:
        return head
    return head + "\nFix:\n" + "\n".join(f"- {issue}" for issue in review.issues)


def fact_check_text(report: FactCheckReport) -> str:
    unsupported = [c for c in report.claims if c.verdict == "unsupported"]
    supported = len(report.claims) - len(unsupported)
    lines = [f"{supported} supported, {len(unsupported)} unsupported."]
    if unsupported:
        lines.append("Unsupported (remove or rewrite):")
        lines.extend(f"- {c.claim}" for c in unsupported)
    return "\n".join(lines)


def _state_dict(ctx: CallbackContext, key: str) -> dict[str, Any] | None:
    value = ctx.state.get(key)
    return value if isinstance(value, dict) else None


def publish_outline(callback_context: CallbackContext) -> types.Content | None:
    data = _state_dict(callback_context, "outline")
    if data is not None:
        callback_context.state["outline_text"] = outline_text(Outline.model_validate(data))
    return None


def publish_review(callback_context: CallbackContext) -> types.Content | None:
    data = _state_dict(callback_context, "review")
    if data is not None:
        review = Review.model_validate(data)
        callback_context.state["review_text"] = review_text(review)
        history = list(callback_context.state.get(REVIEW_HISTORY_KEY) or [])
        history.append({"score": review.score, "approved": review.approved})
        callback_context.state[REVIEW_HISTORY_KEY] = history
    return None


def publish_fact_check(callback_context: CallbackContext) -> types.Content | None:
    data = _state_dict(callback_context, "fact_check")
    if data is not None:
        report = FactCheckReport.model_validate(data)
        callback_context.state["fact_check_text"] = fact_check_text(report)
    return None
