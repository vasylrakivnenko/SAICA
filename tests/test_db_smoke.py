"""End-to-end smoke test for pipeline.db against a live Postgres.

Run with:

    .venv/bin/python -m tests.test_db_smoke

or under pytest. Uses whatever ``POSTGRES_URL`` is configured.
"""

from __future__ import annotations

import sys

from pipeline import db


def run() -> int:
    # Re-init from scratch so counts are predictable.
    db.init_schema(drop_first=True)

    # --- raw_search_results ---
    rid = db.insert_raw_result(
        "perplexity",
        "ai coding agent supervision tools",
        url="https://example.com/tool-x",
        title="Tool X",
        snippet="A supervision layer for coding agents.",
        raw_json={"source": "perplexity", "ranked": 1, "score": 0.91},
    )
    assert rid is not None, "expected an id on first insert"

    # Duplicate (same source + url + title -> same content_hash) should be skipped.
    dup = db.insert_raw_result(
        "perplexity",
        "ai coding agent supervision tools",
        url="https://example.com/tool-x",
        title="Tool X",
        snippet="irrelevant; dedupe is over url+title",
        raw_json={"duplicate": True},
    )
    assert dup is None, f"expected duplicate insert to return None, got {dup!r}"

    rows = db.raw_results_by_query("perplexity", "ai coding agent supervision tools")
    assert len(rows) == 1, f"expected 1 row, got {len(rows)}"
    assert rows[0]["title"] == "Tool X"
    assert rows[0]["raw_json"]["score"] == 0.91

    # --- raw_readmes ---
    db.insert_readme("https://github.com/owner/tool-x", "# Tool X\n\nReadme body.")
    db.insert_readme("https://github.com/owner/tool-x", "# Tool X\n\nUpdated body.")

    # --- candidate_tools ---
    cid = db.upsert_candidate_tool(
        source_url="https://github.com/owner/tool-x",
        proposed_id="tool-x",
        name="Tool X",
        summary="Supervision layer for coding agents.",
        nlp_tags={"keywords": ["supervision", "agent"], "failure_modes": ["fabrication"]},
    )
    assert isinstance(cid, int) and cid > 0

    cid2 = db.upsert_candidate_tool(
        source_url="https://github.com/owner/tool-x",
        extracted={"tagline": "Guardrails for agents", "confidence": {"tagline": 0.82}},
    )
    assert cid2 == cid, f"upsert should return same id; got {cid2} vs {cid}"

    pending = db.get_pending("tools", limit=10)
    assert len(pending) == 1
    assert pending[0]["proposed_id"] == "tool-x"
    assert pending[0]["extracted"]["tagline"] == "Guardrails for agents"
    # nlp_tags survived the second upsert (extracted-only) thanks to CASE guard.
    assert pending[0]["nlp_tags"]["failure_modes"] == ["fabrication"]

    db.update_candidate_status("tools", cid, "reviewed", reviewer="vasyl")
    still_pending = db.get_pending("tools")
    assert len(still_pending) == 0

    # --- candidate_papers ---
    pid = db.upsert_candidate_paper(
        source_url="https://arxiv.org/abs/2603.01234",
        proposed_id="smith-2026-supervision",
        title="Supervising Coding Agents at Scale",
        authors=["Smith, A.", "Lee, B."],
        year=2026,
        arxiv_id="2603.01234",
    )
    assert isinstance(pid, int) and pid > 0
    papers_pending = db.get_pending("papers")
    assert len(papers_pending) == 1
    assert papers_pending[0]["authors"] == ["Smith, A.", "Lee, B."]

    print("smoke test OK")
    for name, count in db.table_counts():
        print(f"  {name:25s} count={count}")
    return 0


if __name__ == "__main__":
    sys.exit(run())
