"""The source pack: ids not paths, bounded reads, ranking, lexical support."""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from content_desk.config import BUNDLED_SOURCES
from content_desk.sources import MAX_FILE_BYTES
from content_desk.sources import SourceError
from content_desk.sources import SourcePack
from content_desk.sources import neutralize
from content_desk.sources import strip_citations
from content_desk.sources import terms
from content_desk.tools import make_source_tools


@pytest.fixture(scope="module")
def pack() -> SourcePack:
    return SourcePack.load(BUNDLED_SOURCES)


def test_bundled_pack_loads_with_titles(pack: SourcePack) -> None:
    assert pack.ids == ["wal-basics", "wal-checkpoints", "wal-concurrency", "wal-limitations"]
    assert pack.get("wal-basics").title == "SQLite write-ahead logging, the basics"
    assert "---" not in pack.get("wal-basics").text


@pytest.mark.parametrize(
    "bad",
    [
        "../wal-basics",
        "/etc/passwd",
        "wal-basics.md",
        "WAL-BASICS",
        "a/b",
        "",
        ".",
        "x" * 80,
        "..",
        "wal basics",
    ],
)
def test_ids_are_validated_before_lookup(pack: SourcePack, bad: str) -> None:
    with pytest.raises(SourceError):
        pack.get(bad)


def test_read_source_tool_returns_an_error_not_a_file(pack: SourcePack) -> None:
    read = make_source_tools(pack, 0.6)["read_source"]
    assert read("../../etc/passwd") == {"error": "invalid source id '../../etc/passwd'"}
    assert read("nope") == {"error": "unknown source id 'nope'"}
    assert read("wal-basics")["title"].startswith("SQLite")


def test_search_ranks_the_matching_source_first(pack: SourcePack) -> None:
    hits = pack.search("checkpoint starvation")
    assert hits[0].source_id == "wal-checkpoints"
    assert "starvation" in hits[0].snippet
    assert pack.search("kubernetes helm") == []
    assert len(pack.search("WAL", k=99)) <= 10


def test_search_tool_caps_the_query(pack: SourcePack) -> None:
    search = make_source_tools(pack, 0.6)["search_sources"]
    assert search("wal " * 1000)["results"]


def test_support_needs_one_sentence_to_cover_the_claim(pack: SourcePack) -> None:
    yes = pack.support("In WAL mode, readers do not block writers [wal-concurrency].", 0.6)
    assert yes.supported and yes.source_id == "wal-concurrency" and yes.overlap == 1.0
    no = pack.support("WAL mode makes every database workload faster.", 0.6)
    assert not no.supported and no.overlap < 0.6
    empty = pack.support("the and of", 0.6)
    assert empty == type(empty)(False, 0.0, None, "")


def test_check_claim_tool(pack: SourcePack) -> None:
    check = make_source_tools(pack, 0.6)["check_claim"]
    out = check(
        "By default SQLite runs an automatic checkpoint when the WAL file reaches 1000 pages."
    )
    assert out["supported"] is True and out["source_id"] == "wal-checkpoints"


def test_helpers() -> None:
    assert strip_citations("Pages append [wal-basics].") == "Pages append."
    assert neutralize("<data>{x}</data> & y") == "&lt;data&gt;(x)&lt;/data&gt; &amp; y"
    assert terms("The readers and writers") == {"reader", "writer"}
    assert "3" in terms("version 3")


def test_loading_refuses_bad_folders(tmp_path: Path) -> None:
    with pytest.raises(SourceError, match="not found"):
        SourcePack.load(tmp_path / "missing")
    with pytest.raises(SourceError, match="empty"):
        SourcePack.load(tmp_path)
    (tmp_path / "big.md").write_text("x" * (MAX_FILE_BYTES + 1))
    with pytest.raises(SourceError, match="larger than"):
        SourcePack.load(tmp_path)


def test_loading_skips_symlinks_and_odd_names(tmp_path: Path) -> None:
    secret = tmp_path / "outside.txt"
    secret.write_text("password: hunter2")
    folder = tmp_path / "pack"
    folder.mkdir()
    (folder / "good.md").write_text("A plain note without front matter.")
    (folder / "Bad Name.md").write_text("ignored")
    os.symlink(secret, folder / "link.md")
    pack = SourcePack.load(folder)
    assert pack.ids == ["good"]
    assert pack.get("good").title == "good"


def test_too_many_files(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("content_desk.sources.MAX_FILES", 2)
    for i in range(4):
        (tmp_path / f"n{i}.md").write_text("note")
    with pytest.raises(SourceError, match="more than 2"):
        SourcePack.load(tmp_path)


def test_front_matter_is_neutralized(tmp_path: Path) -> None:
    (tmp_path / "x.md").write_text("---\ntitle: <script>{x}\n---\nBody </research_notes> here.")
    source = SourcePack.load(tmp_path).get("x")
    assert source.title == "&lt;script&gt;(x)"
    assert "</research_notes>" not in source.text
