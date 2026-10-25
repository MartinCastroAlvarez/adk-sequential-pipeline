"""The content desk: one SequentialAgent with a LoopAgent inside.

    content_desk (SequentialAgent)
      researcher    tools: search_sources, read_source   -> research_notes
      outliner      output_schema=Outline                -> outline (+ outline_text)
      revision_loop (LoopAgent, max_iterations)
        writer                                           -> draft
        critic      output_schema=Review, tool exit_loop -> review (+ review_text)
      fact_checker  output_schema=FactCheckReport, tool check_claim -> fact_check
      editor                                             -> final_post

Agents hand work to each other only through session state: ``output_key`` writes
it, ``{placeholder}`` instructions read it.
"""

from __future__ import annotations

import warnings
from collections.abc import Mapping
from collections.abc import Sequence
from typing import Literal

from google.adk.agents import LlmAgent
from google.adk.agents import LoopAgent
from google.adk.agents import SequentialAgent
from google.adk.agents.base_agent import AfterAgentCallback
from google.adk.agents.base_agent import BaseAgent
from google.adk.agents.llm_agent import AfterModelCallback
from google.adk.agents.llm_agent import ToolUnion
from google.adk.models.base_llm import BaseLlm
from google.adk.tools.exit_loop_tool import exit_loop
from google.genai import types
from pydantic import BaseModel

from content_desk import prompts
from content_desk.callbacks import after_model
from content_desk.callbacks import capture_topic
from content_desk.callbacks import make_before_model
from content_desk.callbacks import make_before_tool
from content_desk.callbacks import make_exit_guard
from content_desk.config import Settings
from content_desk.models import ModelFactory
from content_desk.models import default_models
from content_desk.schemas import FactCheckReport
from content_desk.schemas import Outline
from content_desk.schemas import Review
from content_desk.sources import SourcePack
from content_desk.tools import make_source_tools
from content_desk.views import publish_fact_check
from content_desk.views import publish_outline
from content_desk.views import publish_review

ROOT = "content_desk"
LOOP = "revision_loop"
AGENTS = ("researcher", "outliner", "writer", "critic", "fact_checker", "editor")

#: The only tools each agent may call. ``set_model_response`` is the tool ADK adds
#: to an agent that has both tools and an ``output_schema``.
TOOL_ALLOWLIST: Mapping[str, frozenset[str]] = {
    "researcher": frozenset({"search_sources", "read_source"}),
    "outliner": frozenset(),
    "writer": frozenset(),
    "critic": frozenset({"exit_loop", "set_model_response"}),
    "fact_checker": frozenset({"check_claim", "set_model_response"}),
    "editor": frozenset(),
}

#: ``output_key`` of each agent: the state the next agents read.
OUTPUT_KEYS: Mapping[str, str] = {
    "researcher": "research_notes",
    "outliner": "outline",
    "writer": "draft",
    "critic": "review",
    "fact_checker": "fact_check",
    "editor": "final_post",
}


def build_pipeline(
    settings: Settings | None = None,
    models: ModelFactory | Mapping[str, BaseLlm | str] | None = None,
    pack: SourcePack | None = None,
    allowlist: Mapping[str, frozenset[str]] = TOOL_ALLOWLIST,
    extra_tools: Mapping[str, Sequence[ToolUnion]] | None = None,
) -> SequentialAgent:
    """Build the agent tree.

    Args:
        settings: defaults to :meth:`Settings.from_env`.
        models: an agent-name -> model mapping or factory; defaults to the
            provider in ``settings``.
        pack: the source pack; defaults to ``settings.sources_dir``.
        allowlist: tools each agent may call (enforced by ``before_tool_callback``).
        extra_tools: extra tools per agent, outside the allowlist on purpose
            (tests use it to prove the guard refuses them).
    """
    settings = settings or Settings.from_env()
    pack = pack or SourcePack.load(settings.sources_dir)
    if models is None:
        models = default_models(settings)
    pick = models.__getitem__ if isinstance(models, Mapping) else models
    fns = make_source_tools(pack, settings.support_threshold)
    extra = extra_tools or {}

    config = types.GenerateContentConfig(temperature=settings.temperature)
    before_model = make_before_model(settings.max_request_tokens, settings.max_run_tokens)
    before_tool = make_before_tool(allowlist)

    def agent(
        name: str,
        *,
        description: str,
        instruction: str,
        tools: Sequence[ToolUnion] = (),
        output_schema: type[BaseModel] | None = None,
        include_contents: Literal["default", "none"] = "default",
        after_model_callback: AfterModelCallback = after_model,
        after_agent_callback: AfterAgentCallback | None = None,
    ) -> LlmAgent:
        return LlmAgent(
            name=name,
            model=pick(name),
            description=description,
            instruction=instruction,
            tools=[*tools, *extra.get(name, [])],
            output_schema=output_schema,
            output_key=OUTPUT_KEYS[name],
            include_contents=include_contents,
            generate_content_config=config,
            before_model_callback=before_model,
            after_model_callback=after_model_callback,
            before_tool_callback=before_tool,
            after_agent_callback=after_agent_callback,
        )

    researcher = agent(
        "researcher",
        description="Finds facts about the topic in the local source pack.",
        instruction=prompts.RESEARCHER,
        tools=[fns["search_sources"], fns["read_source"]],
    )
    outliner = agent(
        "outliner",
        description="Turns the research notes into a structured outline.",
        instruction=prompts.OUTLINER,
        output_schema=Outline,
        include_contents="none",
        after_agent_callback=publish_outline,
    )
    writer = agent(
        "writer",
        description="Writes (and rewrites) the draft from the outline and the review.",
        instruction=prompts.writer(*settings.target_words),
        include_contents="none",
    )
    critic = agent(
        "critic",
        description="Scores the draft with a rubric; ends the loop when it passes.",
        instruction=prompts.critic(settings.approval_threshold),
        output_schema=Review,
        tools=[exit_loop],
        include_contents="none",
        after_model_callback=[after_model, make_exit_guard(settings.approval_threshold)],
        after_agent_callback=publish_review,
    )
    fact_checker = agent(
        "fact_checker",
        description="Checks every claim of the draft against the sources.",
        instruction=prompts.FACT_CHECKER,
        output_schema=FactCheckReport,
        tools=[fns["check_claim"]],
        include_contents="none",
        after_agent_callback=publish_fact_check,
    )
    editor = agent(
        "editor",
        description="Polishes the draft, drops unsupported claims, adds the sources.",
        instruction=prompts.EDITOR,
        include_contents="none",
    )

    # SequentialAgent and LoopAgent still work in ADK 2.x but are marked deprecated in
    # favour of graph Workflows, which can't yet be LlmAgent sub-agents. Keep the
    # warning out of every import; the README explains the choice.
    with warnings.catch_warnings():
        warnings.filterwarnings(
            "ignore", r".*(Sequential|Loop)Agent is deprecated", DeprecationWarning
        )
        loop = LoopAgent(
            name=LOOP,
            description="Writer and critic, until the critic approves or the rounds run out.",
            sub_agents=[writer, critic],
            max_iterations=settings.max_iterations,
        )
        return SequentialAgent(
            name=ROOT,
            description="Turns a topic and a local source pack into a reviewed blog post.",
            sub_agents=[researcher, outliner, loop, fact_checker, editor],
            before_agent_callback=capture_topic,
        )


def walk(agent: BaseAgent) -> list[BaseAgent]:
    """Every agent in the tree, depth first, root first."""
    found = [agent]
    for child in agent.sub_agents:
        found.extend(walk(child))
    return found
