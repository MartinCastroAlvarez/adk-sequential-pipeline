"""``python -m content_desk "<topic>"``: run the desk once and print the post."""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from collections.abc import Sequence
from dataclasses import replace
from pathlib import Path
from typing import cast

from content_desk.callbacks import BudgetExceededError
from content_desk.config import PROVIDERS
from content_desk.config import ConfigError
from content_desk.config import Provider
from content_desk.config import Settings
from content_desk.mermaid import to_mermaid
from content_desk.pipeline import build_pipeline
from content_desk.runner import run_desk
from content_desk.runner import transcript
from content_desk.sources import SourceError


def parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="content-desk",
        description="Turn a topic and a local source pack into a reviewed blog post "
        "(Google ADK SequentialAgent + LoopAgent).",
    )
    p.add_argument("topic", nargs="?", help='e.g. "SQLite write-ahead logging"')
    p.add_argument("--provider", choices=PROVIDERS, help="default: DESK_PROVIDER or ollama")
    p.add_argument("--model", help="model id for the provider (default: qwen3:4b on ollama)")
    p.add_argument("--sources", type=Path, help="folder of *.md sources (default: bundled pack)")
    p.add_argument("--max-iterations", type=int, help="writer/critic rounds (default 3)")
    p.add_argument("--threshold", type=int, help="critic score to approve, 0-10 (default 8)")
    p.add_argument(
        "--transcript", action="store_true", help="print every tool call and state write"
    )
    p.add_argument("--json", action="store_true", help="print the result as JSON")
    p.add_argument("--mermaid", action="store_true", help="print the agent graph and exit")
    return p


def settings_from(args: argparse.Namespace) -> Settings:
    settings = Settings.from_env()
    provider: Provider = cast(Provider, args.provider or settings.provider)
    model = args.model or settings.model
    if args.provider and not args.model and args.provider != settings.provider:
        model = Settings.from_env({"DESK_PROVIDER": args.provider}).model
    return replace(
        settings,
        provider=provider,
        model=model,
        sources_dir=args.sources or settings.sources_dir,
        max_iterations=(
            settings.max_iterations if args.max_iterations is None else args.max_iterations
        ),
        approval_threshold=settings.approval_threshold
        if args.threshold is None
        else args.threshold,
    )


def main(argv: Sequence[str] | None = None) -> int:
    args = parser().parse_args(argv)
    try:
        settings = settings_from(args)
        root = build_pipeline(settings)
    except (ConfigError, SourceError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    if args.mermaid:
        print(to_mermaid(root))
        return 0
    if not args.topic:
        print('error: give a topic, e.g. python -m content_desk "SQLite WAL"', file=sys.stderr)
        return 2
    try:
        result = asyncio.run(run_desk(args.topic, root=root))
    except BudgetExceededError as exc:
        print(f"stopped by the token budget: {exc}", file=sys.stderr)
        return 3
    if args.json:
        print(json.dumps(result.to_json(), indent=2, default=str))
        return 0
    if args.transcript:
        print("\n".join(transcript(result)))
        print()
    print(result.final_post.rstrip())
    return 0
