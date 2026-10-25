"""Guardrails, written as ADK callbacks.

* ``before_model``: redact PII from everything the model is about to read, then
  enforce a per-request and a per-run token budget (approximate: 4 chars/token).
* ``after_model``: redact PII from what the model wrote (so it never reaches state),
  and count its tokens.
* ``exit_guard`` (critic only, after model): the critic may end the loop only in the
  same turn as a passing verdict; an ``exit_loop`` call next to a failing score is
  removed.
* ``before_tool``: a per-agent tool allowlist; anything else is refused before it runs.
* ``capture_topic`` (root, before agent): the user's message becomes ``state["topic"]``.

Every intervention is appended to ``state["guardrail_events"]``.
"""

from __future__ import annotations

import json
import re
from collections.abc import Callable
from collections.abc import Mapping
from typing import Any

from google.adk.agents.callback_context import CallbackContext
from google.adk.models.llm_request import LlmRequest
from google.adk.models.llm_response import LlmResponse
from google.adk.tools.base_tool import BaseTool
from google.adk.tools.tool_context import ToolContext
from google.genai import types

from content_desk.sources import neutralize

EVENTS_KEY = "guardrail_events"
TOKENS_KEY = "guardrail_tokens"
MAX_TOPIC_CHARS = 200
EXIT_TOOL = "exit_loop"
RESPONSE_TOOL = "set_model_response"
RUN_KEYS = (
    "research_notes",
    "outline",
    "outline_text",
    "draft",
    "review",
    "review_text",
    "review_history",
    "fact_check",
    "fact_check_text",
    "final_post",
    EVENTS_KEY,
    TOKENS_KEY,
)

_PII_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("email", re.compile(r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b")),
    ("api_key", re.compile(r"\b(?:sk-[A-Za-z0-9_-]{16,}|AIza[0-9A-Za-z_-]{30,})\b")),
    ("card", re.compile(r"\b(?:\d[ -]?){13,19}\b")),
    ("ssn", re.compile(r"\b\d{3}-\d{2}-\d{4}\b")),
    ("phone", re.compile(r"(?<![\w-])\+?\d{1,3}[ .-]?\(?\d{2,4}\)?[ .-]\d{3,4}[ .-]\d{3,4}\b")),
    ("ipv4", re.compile(r"\b(?:\d{1,3}\.){3}\d{1,3}\b")),
)


class BudgetExceededError(RuntimeError):
    """A model call would go over the request or run token budget."""


def redact(text: str) -> tuple[str, int]:
    """Replace emails, keys, card/SSN/phone numbers and IPs with ``[REDACTED:<kind>]``."""
    count = 0
    for kind, pattern in _PII_PATTERNS:
        text, n = pattern.subn(f"[REDACTED:{kind}]", text)
        count += n
    return text, count


def estimate_tokens(text: str) -> int:
    return (len(text) + 3) // 4


def record(state: Any, agent: str, kind: str, detail: str) -> None:
    events = list(state.get(EVENTS_KEY) or [])
    events.append({"agent": agent, "kind": kind, "detail": detail[:300]})
    state[EVENTS_KEY] = events


def _redact_parts(parts: list[types.Part] | None) -> int:
    count = 0
    for part in parts or []:
        if part.text:
            part.text, n = redact(part.text)
            count += n
    return count


def _request_text(request: LlmRequest) -> str:
    chunks: list[str] = []
    system = request.config.system_instruction if request.config else None
    if isinstance(system, str):
        chunks.append(system)
    for content in request.contents:
        for part in content.parts or []:
            if part.text:
                chunks.append(part.text)
            if part.function_call:
                chunks.append(json.dumps(part.function_call.args or {}, default=str))
            if part.function_response:
                chunks.append(json.dumps(part.function_response.response or {}, default=str))
    return "\n".join(chunks)


BeforeModel = Callable[[CallbackContext, LlmRequest], LlmResponse | None]
AfterModel = Callable[[CallbackContext, LlmResponse], LlmResponse | None]
BeforeTool = Callable[[BaseTool, dict[str, Any], ToolContext], dict[str, Any] | None]


def make_before_model(max_request_tokens: int, max_run_tokens: int) -> BeforeModel:
    def before_model(ctx: CallbackContext, request: LlmRequest) -> LlmResponse | None:
        redactions = 0
        if request.config and isinstance(request.config.system_instruction, str):
            request.config.system_instruction, redactions = redact(
                request.config.system_instruction
            )
        for content in request.contents:
            redactions += _redact_parts(content.parts)
        if redactions:
            record(ctx.state, ctx.agent_name, "pii_redacted", f"{redactions} in the request")

        tokens = estimate_tokens(_request_text(request))
        used = int(ctx.state.get(TOKENS_KEY) or 0)
        if tokens > max_request_tokens:
            record(ctx.state, ctx.agent_name, "budget", f"request of ~{tokens} tokens refused")
            raise BudgetExceededError(
                f"{ctx.agent_name}: request of ~{tokens} tokens is over the "
                f"{max_request_tokens}-token request budget"
            )
        if used + tokens > max_run_tokens:
            record(ctx.state, ctx.agent_name, "budget", f"run budget spent at ~{used} tokens")
            raise BudgetExceededError(
                f"{ctx.agent_name}: the run has used ~{used} tokens; another ~{tokens} "
                f"would pass the {max_run_tokens}-token run budget"
            )
        ctx.state[TOKENS_KEY] = used + tokens
        return None

    return before_model


def after_model(ctx: CallbackContext, response: LlmResponse) -> LlmResponse | None:
    """Redact PII from the model's text and count its tokens."""
    if not response.content:
        return None
    redactions = _redact_parts(response.content.parts)
    if redactions:
        record(ctx.state, ctx.agent_name, "pii_redacted", f"{redactions} in the response")
    produced = sum(estimate_tokens(p.text or "") for p in response.content.parts or [])
    ctx.state[TOKENS_KEY] = int(ctx.state.get(TOKENS_KEY) or 0) + produced
    return None


def make_exit_guard(threshold: int) -> AfterModel:
    """Drop an ``exit_loop`` call unless the same turn sets a passing verdict."""

    def exit_guard(ctx: CallbackContext, response: LlmResponse) -> LlmResponse | None:
        if not response.content or not response.content.parts:
            return None
        parts = response.content.parts
        calls = [p.function_call for p in parts if p.function_call]
        if not any(c.name == EXIT_TOOL for c in calls):
            return None
        verdict = next((c.args or {} for c in calls if c.name == RESPONSE_TOOL), None)
        score = verdict.get("score") if verdict else None
        passing = (
            isinstance(score, int)
            and score >= threshold
            and verdict is not None
            and verdict.get("approved") is True
        )
        if passing:
            return None
        detail = (
            "exit_loop without a verdict in the same turn"
            if verdict is None
            else f"exit_loop with score {score} (threshold {threshold}, "
            f"approved={verdict.get('approved')})"
        )
        record(ctx.state, ctx.agent_name, "exit_blocked", detail)
        response.content.parts = [
            p for p in parts if not (p.function_call and p.function_call.name == EXIT_TOOL)
        ]
        return None

    return exit_guard


def make_before_tool(allowlist: Mapping[str, frozenset[str]]) -> BeforeTool:
    """Refuse any tool call not on the calling agent's allowlist."""

    def before_tool(
        tool: BaseTool, args: dict[str, Any], tool_context: ToolContext
    ) -> dict[str, Any] | None:
        agent = tool_context.agent_name
        if tool.name in allowlist.get(agent, frozenset()):
            return None
        record(tool_context.state, agent, "tool_blocked", f"{tool.name} is not allowed")
        return {"error": f"tool {tool.name!r} is not allowed for agent {agent!r}"}

    return before_tool


def capture_topic(callback_context: CallbackContext) -> types.Content | None:
    """Root ``before_agent_callback``: the user's message becomes ``state["topic"]``.

    Runs once per invocation. The topic is redacted, capped and neutralized before any
    agent sees it, and the previous run's keys are cleared, so a second topic in the
    same session starts from a clean desk.
    """
    state = callback_context.state
    content = callback_context.user_content
    text = " ".join(p.text for p in (content.parts if content else None) or [] if p.text)
    text = " ".join(text.split())[:MAX_TOPIC_CHARS]
    if not text:
        text = str(state.get("topic") or "")[:MAX_TOPIC_CHARS]
    if not text:
        return types.Content(role="model", parts=[types.Part(text="Send a topic for the post.")])
    for key in RUN_KEYS:  # a new assignment: nothing from the last run leaks in
        if state.get(key) is not None:
            state[key] = None
    text, n = redact(text)
    text = neutralize(text)
    if n:
        record(state, callback_context.agent_name, "pii_redacted", f"{n} in the topic")
    state["topic"] = text
    return None
