"""Run the desk with ADK's ``Runner`` + ``InMemorySessionService`` and keep a transcript."""

from __future__ import annotations

import json
from dataclasses import dataclass
from dataclasses import field
from typing import Any

from google.adk.agents.base_agent import BaseAgent
from google.adk.events.event import Event
from google.adk.runners import Runner
from google.adk.sessions import InMemorySessionService
from google.genai import types

from content_desk.callbacks import EVENTS_KEY
from content_desk.config import Settings
from content_desk.pipeline import build_pipeline

APP_NAME = "content_desk"


@dataclass
class DeskResult:
    """What a run produced: the final post, the whole state and every event."""

    final_post: str
    state: dict[str, Any]
    events: list[Event] = field(default_factory=list)

    @property
    def authors(self) -> list[str]:
        """Agent names in the order they produced events, consecutive repeats folded."""
        order: list[str] = []
        for event in self.events:
            if event.author != "user" and (not order or order[-1] != event.author):
                order.append(event.author)
        return order

    @property
    def guardrail_events(self) -> list[dict[str, str]]:
        return list(self.state.get(EVENTS_KEY) or [])

    def to_json(self) -> dict[str, Any]:
        keys = ("topic", "outline", "review", "review_history", "fact_check", "guardrail_events")
        return {
            "final_post": self.final_post,
            "agents": self.authors,
            **{k: self.state.get(k) for k in keys},
        }


async def run_desk(
    topic: str,
    settings: Settings | None = None,
    root: BaseAgent | None = None,
    user_id: str = "local",
) -> DeskResult:
    """Run one topic through the desk in a fresh in-memory session."""
    root = root or build_pipeline(settings)
    sessions = InMemorySessionService()
    runner = Runner(agent=root, app_name=APP_NAME, session_service=sessions)
    session = await sessions.create_session(app_name=APP_NAME, user_id=user_id)
    message = types.Content(role="user", parts=[types.Part(text=topic)])
    events = [
        event
        async for event in runner.run_async(
            user_id=user_id, session_id=session.id, new_message=message
        )
    ]
    done = await sessions.get_session(app_name=APP_NAME, user_id=user_id, session_id=session.id)
    state = dict(done.state) if done else {}
    return DeskResult(final_post=str(state.get("final_post") or ""), state=state, events=events)


def _short(value: Any, limit: int = 90) -> str:
    text = value if isinstance(value, str) else json.dumps(value, default=str)
    text = " ".join(text.split())
    return text if len(text) <= limit else text[: limit - 3] + "..."


def transcript(result: DeskResult) -> list[str]:
    """One line per model turn, tool call and state write, in order."""
    lines: list[str] = []
    for event in result.events:
        who = f"[{event.author}]"
        for part in event.content.parts if event.content and event.content.parts else []:
            if part.function_call:
                args = _short(part.function_call.args or {}, 70)
                lines.append(f"{who} -> {part.function_call.name}({args})")
            elif part.function_response:
                lines.append(
                    f"{who} <- {part.function_response.name}: "
                    f"{_short(part.function_response.response or {}, 70)}"
                )
        for key, value in event.actions.state_delta.items():
            if value is not None and key in {
                "research_notes",
                "outline",
                "draft",
                "review",
                "fact_check",
                "final_post",
            }:
                lines.append(f"{who} state[{key!r}] = {_short(value)}")
        if event.actions.escalate:
            lines.append(f"{who} escalate: the loop ends here")
    return lines
