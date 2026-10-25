# Contributing to adk-sequential-pipeline

## TL;DR

```bash
python3 -m venv .venv && . .venv/bin/activate && pip install poetry
poetry install
poetry run pytest
poetry run ruff check content_desk tests examples && poetry run ruff format --check content_desk tests examples
poetry run mypy content_desk
poetry run bandit -c pyproject.toml -q -r content_desk
poetry run pip-audit --ignore-vuln CVE-2026-114603   # see SECURITY.md
poetry run python -m examples.quickstart
DESK_PROVIDER=stub poetry run adk eval content_desk evals/content_desk.evalset.json --config_file_path evals/test_config.json
```

Open a PR against `main` from a `feat/...`, `fix/...`, `docs/...` or `chore/...` branch.

## What this project will not accept

- Tests or CI that call a real model or touch the network.
- A tool that takes a file path, a URL or a shell command.
- A tool added to an agent without adding it to `TOOL_ALLOWLIST` and a test.
- Hosted providers turned on by default.

## What it does accept

- More agents or stages with a clear single job (an SEO pass, a style linter), each with a
  scripted test of its place in the order and its state keys.
- A better `check_claim` (an NLI model, embeddings) that stays local and keeps the
  "single sentence of evidence" contract.
- A `Workflow` (ADK 2.x graph) version of the same tree next to the classic one.
- More eval cases, recorded from the stub, and hardening, each with a hostile test.

## Re-recording the eval set

The eval set holds the stub's exact output. If you change the stub, prompts that the stub
reads, or the source pack, re-record `evals/content_desk.evalset.json` from a stub run and
explain the diff in the PR.

## House rules

1. Tests alongside features; security-relevant changes get a hostile case.
2. README, ARCHITECTURE/SECURITY (when relevant) and CHANGELOG change with the code.
3. No secrets in commits; `.env.example` holds defaults only.
