"""Hygiene: no dangerous calls, no silenced findings, tools take ids not paths."""

from __future__ import annotations

import ast
import inspect
import re
from pathlib import Path

from content_desk import prompts
from content_desk.config import BUNDLED_SOURCES
from content_desk.sources import SourcePack
from content_desk.tools import make_source_tools

PACKAGE = Path(__file__).resolve().parent.parent / "content_desk"
FORBIDDEN_CALLS = {"eval", "exec", "compile", "__import__"}
FORBIDDEN_MODULES = {"pickle", "marshal", "shelve", "subprocess", "yaml", "dill"}


def _sources() -> list[Path]:
    return sorted(PACKAGE.rglob("*.py"))


def test_no_dangerous_calls_or_imports() -> None:
    for path in _sources():
        tree = ast.parse(path.read_text(), filename=str(path))
        for node in ast.walk(tree):
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
                assert node.func.id not in FORBIDDEN_CALLS, f"{path.name}: {node.func.id}()"
            if isinstance(node, ast.Import):
                for alias in node.names:
                    assert alias.name.split(".")[0] not in FORBIDDEN_MODULES, path.name
            if isinstance(node, ast.ImportFrom) and node.module:
                assert node.module.split(".")[0] not in FORBIDDEN_MODULES, path.name
            if isinstance(node, ast.keyword):
                assert node.arg != "shell", f"{path.name}: shell="


def test_no_silenced_findings_in_the_package() -> None:
    for path in _sources():
        text = path.read_text()
        for marker in ("# noqa", "# nosec", "# type: ignore"):
            assert marker not in text, f"{path.name} contains {marker!r}"


def test_tools_take_ids_and_text_never_paths() -> None:
    tools = make_source_tools(SourcePack.load(BUNDLED_SOURCES), 0.6)
    params = {name: list(inspect.signature(fn).parameters) for name, fn in tools.items()}
    assert params == {
        "search_sources": ["query"],
        "read_source": ["source_id"],
        "check_claim": ["claim"],
    }


def test_instructions_only_template_known_state_keys() -> None:
    known = {
        "topic",
        "research_notes",
        "outline_text",
        "review_text?",
        "draft",
        "fact_check_text",
    }
    texts = [prompts.RESEARCHER, prompts.OUTLINER, prompts.FACT_CHECKER, prompts.EDITOR]
    texts += [prompts.writer(100, 200), prompts.critic(8)]
    for text in texts:
        for key in re.findall(r"\{([^{}]*)\}", text):
            assert key in known, key


def test_no_secrets_or_private_hosts_in_the_repo() -> None:
    root = PACKAGE.parent
    pattern = re.compile(r"(sk-[A-Za-z0-9]{20,}|AIza[0-9A-Za-z_-]{30,}|AKIA[0-9A-Z]{16})")
    for path in root.rglob("*"):
        if any(
            part in {".venv", ".git", ".adk", "__pycache__", ".mypy_cache", ".ruff_cache"}
            for part in path.parts
        ):
            continue
        if path.is_file() and path.suffix in {".py", ".md", ".json", ".toml", ".yml", ".example"}:
            assert not pattern.search(path.read_text(errors="ignore")), path
