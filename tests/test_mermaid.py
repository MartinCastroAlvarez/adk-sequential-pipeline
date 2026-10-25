from __future__ import annotations

from content_desk.mermaid import to_mermaid
from content_desk.pipeline import build_pipeline


def test_mermaid_is_generated_from_the_tree(settings) -> None:
    chart = to_mermaid(build_pipeline(settings))
    assert chart.splitlines()[0] == "flowchart TB"
    assert 'subgraph content_desk ["SequentialAgent content_desk"]' in chart
    assert 'subgraph revision_loop ["LoopAgent revision_loop · max 3"]' in chart
    assert 'critic -. "not approved: next round" .-> writer' in chart
    assert 'critic == "exit_loop (escalate) or max rounds" ==> fact_checker' in chart
    for edge in ("researcher --> outliner", "outliner --> writer", "fact_checker --> editor"):
        assert edge in chart
    assert "tools: read_source, search_sources" in chart
    assert "schema: Review" in chart
    assert "→ state.final_post" in chart
