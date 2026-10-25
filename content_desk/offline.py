"""``OfflineDeskModel``: a deterministic stand-in for an LLM, one instance per role.

It reads what a real model would read (the rendered instruction and the tool
results in the request) and answers the way the instruction asks, with plain
string processing: it copies facts from the sources, counts citations for the
rubric, and so on. It is not clever, but it exercises every path of the pipeline
(tool calls, structured output, the loop's exit) with no model and no network.

One behaviour is planted on purpose: the first sentence of every draft is a claim
no source supports, so the fact-checker has something to catch and the editor has
something to remove.
"""

from __future__ import annotations

import math
import re
from typing import Any

from google.adk.models.llm_request import LlmRequest

from content_desk.schemas import ClaimCheck
from content_desk.schemas import FactCheckReport
from content_desk.schemas import Outline
from content_desk.schemas import Review
from content_desk.schemas import Rubric
from content_desk.schemas import Section
from content_desk.sources import split_sentences
from content_desk.sources import strip_citations
from content_desk.stub import Reply
from content_desk.stub import StubLlm
from content_desk.stub import ToolCall
from content_desk.stub import last_function_responses
from content_desk.stub import system_text

_NOTE_HEADER = re.compile(r"^## \[([a-z0-9][a-z0-9-]*)\] (.+)$")
_OUTLINE_SECTION = re.compile(r"^## (.+?)(?: \(sources: ([a-z0-9, -]+)\))?$")
_CITED = re.compile(r"\[[a-z0-9][a-z0-9-]*\]\W*$")
NO_SOURCES = "No source in the pack covers this topic."


def block(text: str, tag: str) -> str:
    """The text between ``<tag>`` and ``</tag>`` (first occurrence), stripped."""
    start, end = text.find(f"<{tag}>"), text.find(f"</{tag}>")
    if start == -1 or end == -1 or end < start:
        return ""
    return text[start + len(tag) + 2 : end].strip()


def parse_notes(notes: str) -> list[tuple[str, str, list[str]]]:
    """``## [id] Title`` + ``- fact`` lines -> ``[(id, title, facts)]``."""
    found: list[tuple[str, str, list[str]]] = []
    for line in notes.splitlines():
        line = line.strip()
        header = _NOTE_HEADER.match(line)
        if header:
            found.append((header.group(1), header.group(2), []))
        elif line.startswith("- ") and found:
            found[-1][2].append(line[2:].strip())
    return found


def parse_outline(text: str) -> tuple[str, list[tuple[str, list[str], list[str]]]]:
    """``outline_text`` -> ``(title, [(heading, source_ids, points)])``."""
    title = ""
    sections: list[tuple[str, list[str], list[str]]] = []
    for line in text.splitlines():
        line = line.strip()
        if line.startswith("# "):
            title = line[2:].strip()
        elif line.startswith("## "):
            match = _OUTLINE_SECTION.match(line)
            heading = match.group(1) if match else line[3:]
            ids = (
                [i.strip() for i in (match.group(2) or "").split(",") if i.strip()] if match else []
            )
            sections.append((heading, ids, []))
        elif line.startswith("- ") and sections:
            sections[-1][2].append(line[2:].strip())
    return title, sections


def draft_sentences(draft: str) -> list[str]:
    """Every sentence of the draft's paragraphs (headings and lists excluded)."""
    sentences: list[str] = []
    for paragraph in draft.split("\n\n"):
        paragraph = paragraph.strip()
        if not paragraph or paragraph.startswith(("#", "- ")):
            continue
        sentences.extend(split_sentences(" ".join(paragraph.split())))
    return sentences


def cite(sentence: str, source_id: str) -> str:
    body = sentence.rstrip().rstrip(".")
    return f"{body} [{source_id}]."


def planted_claim(topic: str) -> str:
    return f"Turning on {topic} makes every database workload faster."


class OfflineDeskModel(StubLlm):
    """Answers as ``role`` (``researcher``, ``outliner``, ``writer``, ...)."""

    role: str
    threshold: int = 8
    support_threshold: float = 0.6
    target_words: tuple[int, int] = (120, 900)

    def reply(self, request: LlmRequest) -> Reply:
        system = system_text(request)
        responses = last_function_responses(request)
        handler = getattr(self, f"_{self.role}", None)
        if handler is None:
            raise ValueError(f"OfflineDeskModel has no role {self.role!r}")
        result: Reply = handler(system, responses)
        return result

    # -- researcher: search, read, then notes --------------------------------------
    def _researcher(self, system: str, responses: list[tuple[str, dict[str, Any]]]) -> Reply:
        names = {name for name, _ in responses}
        if "read_source" in names:
            notes = []
            for _, source in responses:
                if "error" in source:
                    continue
                facts = split_sentences(str(source.get("text", "")))[:4]
                notes.append(f"## [{source['source_id']}] {source['title']}")
                notes.extend(f"- {fact}" for fact in facts)
            return "\n".join(notes) or NO_SOURCES
        if "search_sources" in names:
            results = responses[0][1].get("results", [])
            if not results:
                return NO_SOURCES
            return [ToolCall("read_source", {"source_id": r["source_id"]}) for r in results[:3]]
        return ToolCall("search_sources", {"query": block(system, "topic")})

    # -- outliner: one section per source ------------------------------------------
    def _outliner(self, system: str, responses: list[tuple[str, dict[str, Any]]]) -> Reply:
        topic = block(system, "topic")
        notes = parse_notes(block(system, "research_notes"))
        sections = [
            Section(heading=title[:120], key_points=facts[:3], source_ids=[source_id])
            for source_id, title, facts in notes
            if facts
        ][:5]
        if not sections:
            sections = [Section(heading="What the sources cover", key_points=[NO_SOURCES])]
        return Outline(title=f"A practical guide to {topic}"[:160], sections=sections)

    # -- writer: draft, then revise with citations once the critic asks -----------
    def _writer(self, system: str, responses: list[tuple[str, dict[str, Any]]]) -> Reply:
        title, sections = parse_outline(block(system, "outline"))
        review = block(system, "review").lower()
        with_citations = "cite" in review
        subject = title.removeprefix("A practical guide to ") or "this topic"
        lines = [f"# {title}", "", planted_claim(subject), ""]
        for heading, ids, points in sections:
            source = ids[0] if ids else ""
            body = [cite(p, source) if with_citations and source else p for p in points]
            lines.extend([f"## {heading}", "", " ".join(body), ""])
        return "\n".join(lines).strip() + "\n"

    # -- critic: a rubric computed from the draft ------------------------------------
    def _critic(self, system: str, responses: list[tuple[str, dict[str, Any]]]) -> Reply:
        _, sections = parse_outline(block(system, "outline"))
        draft = block(system, "draft")
        headings = {line[3:].strip() for line in draft.splitlines() if line.startswith("## ")}
        covered = sum(1 for heading, _, _ in sections if heading in headings)
        coverage = math.floor(3 * covered / len(sections)) if sections else 0
        sentences = draft_sentences(draft)
        cited = sum(1 for s in sentences if _CITED.search(s))
        citations = math.floor(4 * cited / len(sentences)) if sentences else 0
        has_intro = draft.startswith("# ") and bool(draft.split("## ")[0].count("\n\n"))
        structure = 1 if has_intro else 0
        words = len(draft.split())
        low, high = self.target_words
        length = 2 if low <= words <= high else (1 if low // 2 <= words <= high * 2 else 0)
        issues = []
        if covered < len(sections):
            issues.append(f"Cover every outline section: {covered} of {len(sections)} found.")
        if cited < len(sentences):
            issues.append(
                f"Cite a source for every factual sentence: {cited} of {len(sentences)} "
                "end with a [source-id]."
            )
        if not structure:
            issues.append('Start with a "# " title and an introduction paragraph.')
        if length < 2:
            issues.append(f"Aim for {low}-{high} words; the draft has {words}.")
        score = coverage + citations + structure + length
        approved = score >= self.threshold
        review = Review(
            score=score,
            rubric=Rubric(
                coverage=coverage, citations=citations, structure=structure, length=length
            ),
            issues=issues,
            approved=approved,
        )
        calls = [ToolCall("set_model_response", review.model_dump())]
        if approved:
            calls.append(ToolCall("exit_loop"))
        return calls

    # -- fact-checker: check_claim per sentence, then the report ---------------------
    def _fact_checker(self, system: str, responses: list[tuple[str, dict[str, Any]]]) -> Reply:
        checks = [r for name, r in responses if name == "check_claim"]
        if not checks:
            claims = [strip_citations(s) for s in draft_sentences(block(system, "draft"))]
            return [ToolCall("check_claim", {"claim": c}) for c in claims if c]
        report = FactCheckReport(
            claims=[
                ClaimCheck(
                    claim=str(r.get("claim", ""))[:600] or "?",
                    verdict="supported" if r.get("supported") else "unsupported",
                    source_id=r.get("source_id") if r.get("supported") else None,
                    evidence=str(r.get("evidence", ""))[:600] if r.get("supported") else "",
                )
                for r in checks
            ],
            unsupported_count=sum(1 for r in checks if not r.get("supported")),
        )
        return ToolCall("set_model_response", report.model_dump())

    # -- editor: drop unsupported sentences, add the sources -------------------------
    def _editor(self, system: str, responses: list[tuple[str, dict[str, Any]]]) -> Reply:
        draft = block(system, "draft")
        fact_check = block(system, "fact_check")
        unsupported = {
            line[2:].strip()
            for line in fact_check.split("Unsupported (remove or rewrite):")[-1].splitlines()
            if line.startswith("- ") and "Unsupported" in fact_check
        }
        titles = {sid: title for sid, title, _ in parse_notes(block(system, "research_notes"))}
        out: list[str] = []
        for paragraph in draft.strip().split("\n\n"):
            paragraph = paragraph.strip()
            if paragraph.startswith("#"):
                out.append(paragraph)
                continue
            kept = [s for s in split_sentences(paragraph) if strip_citations(s) not in unsupported]
            if kept:
                out.append(" ".join(kept))
            elif len(out) == 1:  # the introduction was all unsupported: say what follows
                out.append("What follows is taken from the cited sources only.")
        cited = list(dict.fromkeys(re.findall(r"\[([a-z0-9][a-z0-9-]*)\]", "\n".join(out))))
        if cited:
            out.append("## Sources")
            out.append("\n".join(f"- [{sid}] {titles.get(sid, sid)}" for sid in cited))
        return "\n\n".join(out) + "\n"
