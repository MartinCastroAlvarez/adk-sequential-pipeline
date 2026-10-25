from __future__ import annotations

import pytest
from google.adk.models.llm_request import LlmRequest

from content_desk.schemas import Outline
from content_desk.schemas import Section
from content_desk.stub import ScriptedLlm
from content_desk.stub import ToolCall
from content_desk.stub import last_function_responses
from content_desk.stub import to_parts


def test_reply_shapes() -> None:
    assert to_parts("hi")[0].text == "hi"
    assert to_parts({"a": 1})[0].text == '{"a": 1}'
    outline = Outline(title="t", sections=[Section(heading="h", key_points=["p"])])
    assert to_parts(outline)[0].text.startswith('{"title":"t"')
    call = to_parts(ToolCall("exit_loop"))[0].function_call
    assert call is not None and call.name == "exit_loop"


async def test_scripted_llm_records_and_runs_out() -> None:
    model = ScriptedLlm(script=["one"])
    replies = [r async for r in model.generate_content_async(LlmRequest())]
    assert replies[0].content.parts[0].text == "one"
    assert replies[0].usage_metadata.total_token_count == 0
    assert model.calls == 1
    with pytest.raises(AssertionError, match="script exhausted"):
        model.reply(LlmRequest())
    assert ScriptedLlm(script=["x"], repeat_last=True).reply(LlmRequest()) == "x"


def test_last_function_responses_of_an_empty_request() -> None:
    assert last_function_responses(LlmRequest()) == []
