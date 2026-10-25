# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

## [0.1.0] - 2026-10-25

### Added

- The content desk on google-adk 2.13: `SequentialAgent` of researcher, outliner, a
  `LoopAgent` of writer and critic, fact-checker and editor, exposed as `root_agent` in
  `content_desk/agent.py` for `adk web`, `adk run` and `adk eval`.
- State handoff through `output_key` and `{placeholder}` instructions, with
  `include_contents="none"` downstream and Markdown views of structured outputs.
- Structured outputs (`Outline`, `Review` rubric, `FactCheckReport`), the critic's
  `exit_loop` and ADK's `set_model_response` for schema + tools.
- Guardrail callbacks: topic capture, PII redaction before and after every model call,
  per-request and per-run token budgets, a per-agent tool allowlist, and an exit guard
  that keeps a failing critic from ending the loop.
- Tools over a bundled local source pack (`search_sources`, `read_source`,
  `check_claim`), ids not paths.
- `ScriptedLlm` and `OfflineDeskModel` stub models; an ADK eval set with local metrics;
  `python -m content_desk` (ollama by default, Gemini optional, stub offline) with
  `--transcript`, `--json` and a generated `--mermaid` graph.
