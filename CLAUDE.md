# CLAUDE.md

Contract between this repository and any AI agent contributing to it.

## Required reading

1. This file. 2. [`README.md`](README.md). 3. [`ARCHITECTURE.md`](ARCHITECTURE.md).
4. [`SECURITY.md`](SECURITY.md).

## Mission

`adk-sequential-pipeline` shows the sequential pipeline and the generator-critic loop in
current Google ADK (Python): a `SequentialAgent` with a `LoopAgent` inside, state passed
through `output_key` and `{placeholder}` instructions, guardrails as callbacks, and an ADK
eval set, as small, correct and tested code.

## The rules

1. **Local by default.** ollama on loopback through `LiteLlm` is the default; Gemini stays
   optional. Tests, CI and the eval set use `ScriptedLlm` / `OfflineDeskModel` only.
2. **State is the interface.** Agents read inputs only from placeholders and write one
   `output_key`. A new state key is added to `OUTPUT_KEYS` or the views, and to
   `callbacks.RUN_KEYS` so a new run clears it.
3. **Tools take ids and text.** Never a path, URL or command. Every tool is in
   `TOOL_ALLOWLIST` for exactly the agents that need it, with a test.
4. **Model output is untrusted.** Inputs go inside `<tag>` blocks; structured outputs go
   through the pydantic schemas in `schemas.py`; the critic's `exit_loop` stays guarded.
5. **ADK conventions.** `root_agent` lives in `content_desk/agent.py`; `adk run`,
   `adk eval` and `adk web` must keep working on the stub (CI runs all three).
6. Never add `# noqa`, `# nosec` or `# type: ignore` to the package, skip a test, or
   loosen lint/type/coverage config.

## Done means

`poetry run pytest` (coverage >= 85%), `ruff check`, `ruff format --check`, `mypy`
(strict), `bandit` and `pip-audit` all green; `python -m examples.quickstart` and the
`adk eval` command in CONTRIBUTING pass; README and CHANGELOG are updated.

## Git

Small commits, imperative subjects, never force-push `main`, never commit secrets, `.env`
or `.adk/`.
