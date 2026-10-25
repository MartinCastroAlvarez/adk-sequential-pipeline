"""Run the content desk offline and check what it produced.

python -m examples.quickstart                    # stub models, no network
DESK_PROVIDER=ollama python -m examples.quickstart "SQLite WAL"   # a real local model
"""

from __future__ import annotations

import asyncio
import os
import sys
from dataclasses import replace

from content_desk import Settings
from content_desk import run_desk
from content_desk.runner import transcript


async def main(topic: str) -> int:
    settings = Settings.from_env()
    if "DESK_PROVIDER" not in os.environ:
        settings = replace(settings, provider="stub")
    result = await run_desk(topic, settings)
    print("\n".join(transcript(result)))
    print()
    print(result.final_post)

    state = result.state
    checks = {
        "every agent ran, in order": [a for a in result.authors if a != "content_desk"][:3]
        == ["researcher", "outliner", "writer"]
        and result.authors[-1] == "editor",
        "the critic reviewed at least one draft": bool(state.get("review_history")),
        "the fact-checker reported on every sentence": bool(state["fact_check"]["claims"]),
        "the final post cites its sources": "## Sources" in result.final_post,
    }
    if settings.provider == "stub":
        checks["the loop needed a second round"] = len(state["review_history"]) == 2
        checks["the planted claim was flagged"] = state["fact_check"]["unsupported_count"] == 1
    print("checks:")
    for name, ok in checks.items():
        print(f"  [{'ok' if ok else 'FAIL'}] {name}")
    return 0 if all(checks.values()) else 1


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main(" ".join(sys.argv[1:]) or "SQLite write-ahead logging")))
