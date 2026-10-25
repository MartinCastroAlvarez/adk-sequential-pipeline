"""Function tools over the local source pack. No network, no filesystem paths."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from content_desk.sources import SourceError
from content_desk.sources import SourcePack

MAX_QUERY_CHARS = 300
MAX_CLAIM_CHARS = 600
MAX_READ_CHARS = 4000

ToolFn = Callable[..., dict[str, Any]]


def make_source_tools(pack: SourcePack, support_threshold: float) -> dict[str, ToolFn]:
    """The three tools, closed over one pack. Keys are the tool names the model sees."""

    def search_sources(query: str) -> dict[str, Any]:
        """Search the local source pack.

        Args:
            query: Words to look for, for example the topic of the post.

        Returns:
            Up to five sources, best first, each with an id, a title and a snippet.
        """
        query = str(query)[:MAX_QUERY_CHARS]
        hits = pack.search(query, k=5)
        return {
            "results": [
                {"source_id": h.source_id, "title": h.title, "snippet": h.snippet} for h in hits
            ]
        }

    def read_source(source_id: str) -> dict[str, Any]:
        """Read one source from the local source pack.

        Args:
            source_id: An id returned by search_sources, such as "wal-basics".

        Returns:
            The source's id, title and text, or an error for an unknown id.
        """
        try:
            source = pack.get(source_id)
        except SourceError as exc:
            return {"error": str(exc)}
        return {
            "source_id": source.source_id,
            "title": source.title,
            "text": source.text[:MAX_READ_CHARS],
        }

    def check_claim(claim: str) -> dict[str, Any]:
        """Check one sentence of the draft against the source pack.

        Args:
            claim: One factual sentence, without its citation.

        Returns:
            Whether a single source sentence supports it, that source's id and the
            evidence sentence, plus the share of the claim's words it covers.
        """
        support = pack.support(str(claim)[:MAX_CLAIM_CHARS], support_threshold)
        return {
            "claim": str(claim)[:MAX_CLAIM_CHARS],
            "supported": support.supported,
            "source_id": support.source_id,
            "evidence": support.evidence,
            "overlap": support.overlap,
        }

    return {
        "search_sources": search_sources,
        "read_source": read_source,
        "check_claim": check_claim,
    }
