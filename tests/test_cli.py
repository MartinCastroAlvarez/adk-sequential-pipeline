"""``python -m content_desk``."""

from __future__ import annotations

import json

import pytest

from content_desk.cli import main


@pytest.fixture(autouse=True)
def _stub_env(monkeypatch: pytest.MonkeyPatch) -> None:
    for key in ("DESK_PROVIDER", "DESK_MODEL", "DESK_MAX_RUN_TOKENS", "OLLAMA_HOST"):
        monkeypatch.delenv(key, raising=False)


def test_prints_the_final_post(capsys: pytest.CaptureFixture[str]) -> None:
    assert main(["--provider", "stub", "SQLite WAL"]) == 0
    out = capsys.readouterr().out
    assert out.startswith("# A practical guide to SQLite WAL")
    assert "## Sources" in out


def test_transcript_shows_tools_and_the_loop_exit(capsys: pytest.CaptureFixture[str]) -> None:
    assert main(["--provider", "stub", "--transcript", "SQLite WAL"]) == 0
    out = capsys.readouterr().out
    assert "[researcher] -> search_sources(" in out
    assert "[critic] -> exit_loop({})" in out
    assert "[critic] escalate: the loop ends here" in out
    assert "[editor] state['final_post']" in out


def test_json(capsys: pytest.CaptureFixture[str]) -> None:
    assert main(["--provider", "stub", "--json", "--max-iterations", "1", "SQLite WAL"]) == 0
    data = json.loads(capsys.readouterr().out)
    assert data["agents"][-1] == "editor"
    assert [h["approved"] for h in data["review_history"]] == [False]
    assert data["fact_check"]["unsupported_count"] == 1


def test_threshold_flag(capsys: pytest.CaptureFixture[str]) -> None:
    assert main(["--provider", "stub", "--json", "--threshold", "6", "SQLite WAL"]) == 0
    assert len(json.loads(capsys.readouterr().out)["review_history"]) == 1


def test_mermaid(capsys: pytest.CaptureFixture[str]) -> None:
    assert main(["--provider", "stub", "--mermaid"]) == 0
    assert capsys.readouterr().out.startswith("flowchart TB")


def test_errors(capsys: pytest.CaptureFixture[str], tmp_path, monkeypatch) -> None:
    assert main(["--provider", "stub"]) == 2
    assert main(["--provider", "stub", "--sources", str(tmp_path / "nope"), "x"]) == 2
    assert main(["--provider", "stub", "--max-iterations", "99", "x"]) == 2
    monkeypatch.setenv("DESK_MAX_RUN_TOKENS", "1024")
    assert main(["--provider", "stub", "SQLite WAL"]) == 3
    err = capsys.readouterr().err
    assert "error:" in err and "stopped by the token budget" in err


def test_provider_switch_picks_that_providers_default_model(monkeypatch) -> None:
    from content_desk.cli import parser
    from content_desk.cli import settings_from

    monkeypatch.setenv("DESK_PROVIDER", "stub")
    s = settings_from(parser().parse_args(["--provider", "gemini", "x"]))
    assert (s.provider, s.model) == ("gemini", "gemini-3.5-flash")
    s = settings_from(parser().parse_args(["--model", "llama3.2", "x"]))
    assert (s.provider, s.model) == ("stub", "llama3.2")
