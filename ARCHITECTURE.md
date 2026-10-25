# Architecture

```
content_desk/
  agent.py      root_agent = build_pipeline(Settings.from_env())   <- adk web / run / eval
  pipeline.py   the agent tree, TOOL_ALLOWLIST, OUTPUT_KEYS
  prompts.py    instructions with {placeholders} and <tag> data blocks
  schemas.py    Outline, Review (+ Rubric), FactCheckReport (pydantic, extra="forbid")
  views.py      after_agent callbacks: dict in state -> *_text view for the next prompt
  callbacks.py  guardrails: capture_topic, before/after model, exit_guard, before_tool
  tools.py      search_sources, read_source, check_claim (closures over one SourcePack)
  sources.py    SourcePack: *.md folder -> in-memory index; ids, search, lexical support
  models.py     provider -> model per agent (LiteLlm on ollama, Gemini id, offline stub)
  stub.py       StubLlm, ScriptedLlm (tests), ToolCall
  offline.py    OfflineDeskModel: deterministic per-role model for demo, eval and CI
  runner.py     run_desk(): Runner + InMemorySessionService, DeskResult, transcript()
  mermaid.py    Mermaid flowchart generated from the agent tree
  cli.py        python -m content_desk
  sources/      the bundled source pack (four notes on SQLite WAL)
evals/          ADK eval set + test_config.json (local metrics)
```

## One run

1. `Runner.run_async` starts the root `SequentialAgent`. Its `before_agent_callback`
   (`capture_topic`) clears the previous run's keys and writes the redacted, capped topic
   to `state["topic"]`.
2. **researcher** (`include_contents="default"`, it needs its own tool turns) calls
   `search_sources`, then `read_source` for the best hits, and answers with notes grouped
   by source. ADK saves the text to `research_notes`.
3. **outliner** answers with JSON matching `Outline` (ADK sets the response schema; no
   tools). `publish_outline` writes `outline_text`.
4. **revision_loop** (`LoopAgent`, `max_iterations`) runs **writer** then **critic** until a
   sub-agent escalates or the rounds run out. The writer reads `{outline_text}`,
   `{research_notes}` and `{review_text?}`. The critic has `output_schema=Review` and the
   `exit_loop` tool; because its model can't combine a schema with tools, ADK adds
   `set_model_response` and turns that call into the critic's final answer. `exit_loop`
   sets `actions.escalate`; `exit_guard` removes it first unless the verdict in the same
   response passes. `publish_review` writes `review_text` and appends to
   `review_history`.
5. **fact_checker** calls `check_claim` once per sentence (in parallel, one model turn),
   then returns a `FactCheckReport` via `set_model_response`. `publish_fact_check` writes
   `fact_check_text`.
6. **editor** reads `{draft}`, `{fact_check_text}` and `{research_notes}` and writes
   `final_post`.

Every model call passes `before_model` (PII redaction, token budgets) and `after_model`
(redaction of the answer, token count); every tool call passes `before_tool` (the
allowlist). Interventions are appended to `state["guardrail_events"]`.

## State keys

| Key | Written by | Read by |
| --- | --- | --- |
| `topic` | `capture_topic` | researcher, outliner |
| `research_notes` | researcher (`output_key`) | outliner, writer, editor |
| `outline` / `outline_text` | outliner / `publish_outline` | code / writer, critic |
| `draft` | writer | critic, fact_checker, editor |
| `review` / `review_text` / `review_history` | critic / `publish_review` | code / writer / code |
| `fact_check` / `fact_check_text` | fact_checker / `publish_fact_check` | code / editor |
| `final_post` | editor | the caller |
| `guardrail_events`, `guardrail_tokens` | callbacks | the caller, the budget |

## Models

`build_pipeline(models=...)` asks a factory (or mapping) for each agent's model by name.
`ollama` shares one `LiteLlm("ollama_chat/<model>", api_base=OLLAMA_HOST)`; `gemini`
passes the model id string to ADK; `stub` gives each agent an `OfflineDeskModel` with its
role. Tests pass a mapping of `ScriptedLlm`s, one script per agent, and inspect the
`LlmRequest`s each one recorded.

`StubLlm.capabilities` reports `output_schema_and_tools=False`, like `LiteLlm` on ollama,
so tests exercise the same `set_model_response` path a local model takes.

## Why these choices

- **`include_contents="none"` downstream.** Each agent sees its instruction (with state
  templated in) and its own tool calls only. Prompts stay small, and an agent can't be
  steered by another agent's tool output that it was never meant to read.
- **Views next to dicts.** Placeholders call `str()` on state values; a dict would render
  as a Python repr. Code and tests read the validated dicts; prompts read the Markdown.
- **Guard the exit in code.** `exit_loop` is the model's decision, which is the point of
  the pattern, but a decision that contradicts the model's own score is a bug, so it is
  removed before ADK runs the tool.
- **Lexical `check_claim`.** Free, deterministic and explainable (it returns the evidence
  sentence). Swap it for an NLI or embedding check behind the same tool signature.
