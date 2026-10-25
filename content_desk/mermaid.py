"""A Mermaid flowchart generated from the real agent tree (not drawn by hand)."""

from __future__ import annotations

from google.adk.agents import LlmAgent
from google.adk.agents import LoopAgent
from google.adk.agents import SequentialAgent
from google.adk.agents.base_agent import BaseAgent


def _label(agent: LlmAgent) -> str:
    rows = [f"<b>{agent.name}</b>"]
    tools = [getattr(t, "name", getattr(t, "__name__", "?")) for t in agent.tools]
    if tools:
        rows.append("tools: " + ", ".join(sorted(tools)))
    if agent.output_schema is not None:
        rows.append(f"schema: {getattr(agent.output_schema, '__name__', 'schema')}")
    if agent.output_key:
        rows.append(f"→ state.{agent.output_key}")
    return "<br/>".join(rows)


def _first(agent: BaseAgent) -> str:
    return (
        agent.name
        if isinstance(agent, LlmAgent) or not agent.sub_agents
        else _first(agent.sub_agents[0])
    )


def _last(agent: BaseAgent) -> str:
    if isinstance(agent, LlmAgent) or not agent.sub_agents:
        return agent.name
    return _last(agent.sub_agents[-1])


def _emit(agent: BaseAgent, lines: list[str], indent: str) -> None:
    if isinstance(agent, LlmAgent):
        lines.append(f'{indent}{agent.name}["{_label(agent)}"]')
        return
    kind = type(agent).__name__
    title = f"{kind} {agent.name}"
    if isinstance(agent, LoopAgent) and agent.max_iterations:
        title += f" · max {agent.max_iterations}"
    lines.append(f'{indent}subgraph {agent.name} ["{title}"]')
    lines.append(
        f"{indent}  direction LR" if isinstance(agent, LoopAgent) else f"{indent}  direction TB"
    )
    for child in agent.sub_agents:
        _emit(child, lines, indent + "  ")
    if isinstance(agent, (SequentialAgent, LoopAgent)):
        for a, b in zip(agent.sub_agents, agent.sub_agents[1:], strict=False):
            if isinstance(a, LoopAgent):
                edge = '== "exit_loop (escalate) or max rounds" ==>'
                lines.append(f"{indent}  {_last(a)} {edge} {_first(b)}")
            else:
                lines.append(f"{indent}  {_last(a)} --> {_first(b)}")
    if isinstance(agent, LoopAgent) and agent.sub_agents:
        lines.append(f'{indent}  {_last(agent)} -. "not approved: next round" .-> {_first(agent)}')
    lines.append(f"{indent}end")


def to_mermaid(root: BaseAgent) -> str:
    """``flowchart TB`` for ``root``: sequences chain, loops get a back edge."""
    lines = ["flowchart TB", '  topic(["user: topic"])']
    _emit(root, lines, "  ")
    lines.append(f"  topic --> {_first(root)}")
    lines.append('  post(["final_post"])')
    lines.append(f"  {_last(root)} --> post")
    return "\n".join(lines)
