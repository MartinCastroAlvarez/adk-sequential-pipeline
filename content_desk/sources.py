"""The source pack: a folder of Markdown notes, the only thing the researcher can read.

Every lookup goes through :meth:`SourcePack.get`, which accepts a source id (the file
stem, ``[a-z0-9-]``), never a path, so a model-chosen id can't escape the folder.
Files are loaded once, capped in size and count, and symlinks are refused.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

MAX_FILES = 200
MAX_FILE_BYTES = 64_000
SOURCE_ID_RE = re.compile(r"^[a-z0-9][a-z0-9-]{0,63}$")
_SENTENCE_RE = re.compile(r"(?<=[.!?])\s+")
_WORD_RE = re.compile(r"[a-z0-9_]+")
_CITATION_RE = re.compile(r"\s*\[[a-z0-9][a-z0-9-]{0,63}\]")

_STOPWORDS_TEXT = """
a an and are as at be because been but by can cannot do does each every for from has have
how in into is it its itself not of on one only or so still that the their them then there
these this those to too until up was what when where which while who why will with without
you your after before also more most other same some than very own off over under again
further about against any all both few just should now out may must need needs
"""
STOPWORDS = frozenset(_STOPWORDS_TEXT.split())


class SourceError(ValueError):
    """An invalid source id, or a pack that can't be loaded."""


def terms(text: str) -> set[str]:
    """Content words of ``text``: lower-cased, no stopwords, a crude plural fold."""
    words = set()
    for word in _WORD_RE.findall(text.lower()):
        if word in STOPWORDS or len(word) < 3 and not word.isdigit():
            continue
        if len(word) > 4 and word.endswith("s") and not word.endswith("ss"):
            word = word[:-1]
        words.add(word)
    return words


def split_sentences(text: str) -> list[str]:
    return [s.strip() for s in _SENTENCE_RE.split(text.strip()) if s.strip()]


def strip_citations(text: str) -> str:
    """``"WAL appends pages [wal-basics]."`` -> ``"WAL appends pages."``"""
    return _CITATION_RE.sub("", text).strip()


def neutralize(text: str) -> str:
    """Make source text inert inside a prompt: no tags, no template braces."""
    return (
        text.replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace("{", "(")
        .replace("}", ")")
    )


@dataclass(frozen=True)
class Source:
    source_id: str
    title: str
    text: str

    @property
    def sentences(self) -> list[str]:
        return split_sentences(self.text)


@dataclass(frozen=True)
class Hit:
    source_id: str
    title: str
    score: float
    snippet: str


@dataclass(frozen=True)
class Support:
    supported: bool
    overlap: float
    source_id: str | None
    evidence: str


def _parse(path: Path) -> Source:
    raw = path.read_text(encoding="utf-8")
    title = path.stem.replace("-", " ")
    body = raw
    if raw.startswith("---\n"):
        end = raw.find("\n---", 4)
        if end != -1:
            for line in raw[4:end].splitlines():
                key, _, value = line.partition(":")
                if key.strip() == "title" and value.strip():
                    title = value.strip()
            body = raw[end + 4 :]
    text = " ".join(line.strip() for line in body.splitlines() if line.strip())
    return Source(source_id=path.stem, title=neutralize(title), text=neutralize(text))


class SourcePack:
    """A read-only, in-memory index over ``*.md`` files in one folder."""

    def __init__(self, sources: list[Source]) -> None:
        if not sources:
            raise SourceError("the source pack is empty")
        self._sources = {s.source_id: s for s in sources}

    @classmethod
    def load(cls, folder: Path) -> SourcePack:
        root = folder.resolve()
        if not root.is_dir():
            raise SourceError(f"source folder not found: {folder}")
        sources: list[Source] = []
        for path in sorted(root.glob("*.md")):
            if path.is_symlink() or not path.is_file():
                continue
            if not SOURCE_ID_RE.match(path.stem):
                continue
            if path.stat().st_size > MAX_FILE_BYTES:
                raise SourceError(f"{path.name} is larger than {MAX_FILE_BYTES} bytes")
            sources.append(_parse(path))
            if len(sources) > MAX_FILES:
                raise SourceError(f"more than {MAX_FILES} sources in {folder}")
        return cls(sources)

    @property
    def ids(self) -> list[str]:
        return list(self._sources)

    def get(self, source_id: str) -> Source:
        if not isinstance(source_id, str) or not SOURCE_ID_RE.match(source_id):
            raise SourceError(f"invalid source id {source_id!r}")
        try:
            return self._sources[source_id]
        except KeyError:
            raise SourceError(f"unknown source id {source_id!r}") from None

    def search(self, query: str, k: int = 5) -> list[Hit]:
        """Rank sources by how many query terms they contain (title terms count double)."""
        wanted = terms(query)
        hits: list[Hit] = []
        for source in self._sources.values():
            body, title = terms(source.text), terms(source.title)
            score = sum((2.0 if t in title else 0.0) + (1.0 if t in body else 0.0) for t in wanted)
            if score <= 0:
                continue
            best = max(source.sentences, key=lambda s: len(terms(s) & wanted))
            hits.append(Hit(source.source_id, source.title, score, best[:240]))
        hits.sort(key=lambda h: (-h.score, h.source_id))
        return hits[: max(1, min(k, 10))]

    def support(self, claim: str, threshold: float) -> Support:
        """The source sentence that best covers ``claim``'s content words.

        ``overlap`` is the share of the claim's terms found in that one sentence.
        Lexical, not semantic: it gives the fact-checker evidence to judge, and
        refuses to call a claim supported when no single sentence backs most of it.
        """
        wanted = terms(strip_citations(claim))
        if not wanted:
            return Support(False, 0.0, None, "")
        best: tuple[float, str | None, str] = (0.0, None, "")
        for source in self._sources.values():
            for sentence in source.sentences:
                overlap = len(terms(sentence) & wanted) / len(wanted)
                if overlap > best[0]:
                    best = (overlap, source.source_id, sentence)
        overlap, source_id, evidence = best
        return Support(overlap >= threshold, round(overlap, 2), source_id, evidence[:600])
