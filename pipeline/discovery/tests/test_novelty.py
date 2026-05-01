"""Tests for ``pipeline.discovery.novelty``.

Two layers:
  * Pure tests with a synthetic in-memory KG index (no disk I/O).
  * One end-to-end test that loads the real KG and confirms a known
    tool (semgrep) gets DROPped while a fake one CONTINUEs.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from pipeline.discovery.novelty import (
    CanonicalIds,
    NoveltyOutcome,
    _KgIndex,
    build_kg_index,
    classify,
    extract_canonical_ids,
)


# ---------------------------------------------------------------------------
# Canonical-id extraction
# ---------------------------------------------------------------------------


def test_extract_github_from_source_url() -> None:
    ids = extract_canonical_ids(
        {"source_url": "https://github.com/Foo-Org/Bar-Repo"}
    )
    assert ids.github == "foo-org/bar-repo"


def test_extract_github_strips_dot_git() -> None:
    ids = extract_canonical_ids(
        {"source_url": "https://github.com/x/y.git"}
    )
    assert ids.github == "x/y"


def test_extract_github_from_readme_when_source_url_missing() -> None:
    ids = extract_canonical_ids(
        {"readme": "Install via `pip install x`. Source: https://github.com/x/y."}
    )
    assert ids.github == "x/y"


def test_extract_arxiv_id_from_field() -> None:
    ids = extract_canonical_ids({"arxiv_id": "2304.12345v2"})
    assert ids.arxiv == "2304.12345v2"


def test_extract_arxiv_id_from_summary() -> None:
    ids = extract_canonical_ids(
        {"summary": "See arXiv:2401.00001 for details."}
    )
    assert ids.arxiv == "2401.00001"


def test_extract_doi_from_summary() -> None:
    ids = extract_canonical_ids(
        {"summary": "Published in NeurIPS — DOI 10.5555/abc123."}
    )
    assert ids.doi == "10.5555/abc123"


def test_extract_slug_from_proposed_id() -> None:
    ids = extract_canonical_ids({"proposed_id": "Cool-Tool"})
    assert ids.slug == "cool-tool"


def test_no_ids_returns_empty_canonical() -> None:
    ids = extract_canonical_ids({})
    assert ids == CanonicalIds()


# ---------------------------------------------------------------------------
# Synthetic-index classify
# ---------------------------------------------------------------------------


def _idx_with_one_tool() -> _KgIndex:
    """In-memory index containing just 'foo' tool."""
    idx = _KgIndex()
    foo = {
        "id": "foo",
        "repository_url": "https://github.com/foo-org/foo",
        "addresses_failure_modes": ["fabrication"],
        "cited_in": ["paper-a"],
        "last_updated": "2026-01-01",
    }
    idx.tools["foo"] = foo
    idx.by_github["foo-org/foo"] = "foo"
    idx.by_slug["foo"] = "foo"
    return idx


def test_continue_when_no_canonical_id_matches() -> None:
    decision = classify(
        {"source_url": "https://github.com/new-org/brand-new"},
        kg_index=_idx_with_one_tool(),
    )
    assert decision.outcome == NoveltyOutcome.CONTINUE
    assert decision.matched_tool_id is None


def test_drop_when_known_tool_no_new_evidence() -> None:
    decision = classify(
        {"source_url": "https://github.com/foo-org/foo"},
        kg_index=_idx_with_one_tool(),
    )
    assert decision.outcome == NoveltyOutcome.DROP
    assert decision.matched_tool_id == "foo"
    assert decision.new_evidence == []


def test_update_queue_when_new_failure_mode_hit() -> None:
    decision = classify(
        {
            "source_url": "https://github.com/foo-org/foo",
            "failure_mode_hits": ["scope_creep"],  # not in the existing FMs
        },
        kg_index=_idx_with_one_tool(),
    )
    assert decision.outcome == NoveltyOutcome.UPDATE_QUEUE
    assert any(e.startswith("new_fm_hit:scope_creep") for e in decision.new_evidence)


def test_update_queue_when_new_paper_citation() -> None:
    decision = classify(
        {
            "source_url": "https://github.com/foo-org/foo",
            "paper_citations": ["paper-b"],  # known tool only has paper-a
        },
        kg_index=_idx_with_one_tool(),
    )
    assert decision.outcome == NoveltyOutcome.UPDATE_QUEUE
    assert "new_paper:paper-b" in decision.new_evidence


def test_update_queue_when_newer_release() -> None:
    decision = classify(
        {
            "source_url": "https://github.com/foo-org/foo",
            "last_updated": "2026-04-01",  # newer than 2026-01-01
        },
        kg_index=_idx_with_one_tool(),
    )
    assert decision.outcome == NoveltyOutcome.UPDATE_QUEUE
    assert any(e.startswith("newer_release:") for e in decision.new_evidence)


def test_drop_when_repeated_known_evidence() -> None:
    """Candidate carries the same evidence the tool already has — DROP."""
    decision = classify(
        {
            "source_url": "https://github.com/foo-org/foo",
            "paper_citations": ["paper-a"],   # already in KG
            "failure_mode_hits": ["fabrication"],  # already addresses
            "last_updated": "2026-01-01",   # same date
        },
        kg_index=_idx_with_one_tool(),
    )
    assert decision.outcome == NoveltyOutcome.DROP


def test_slug_match_when_no_repository_url_on_candidate() -> None:
    """Candidate has only proposed_id; slug match alone is enough to
    trigger DROP/UPDATE."""
    decision = classify(
        {"proposed_id": "foo"},
        kg_index=_idx_with_one_tool(),
    )
    assert decision.outcome == NoveltyOutcome.DROP
    assert decision.matched_tool_id == "foo"


def test_invalid_date_does_not_count_as_newer_release() -> None:
    decision = classify(
        {
            "source_url": "https://github.com/foo-org/foo",
            "last_updated": "tomorrow-ish",
        },
        kg_index=_idx_with_one_tool(),
    )
    assert decision.outcome == NoveltyOutcome.DROP


# ---------------------------------------------------------------------------
# End-to-end against the real KG
# ---------------------------------------------------------------------------


def test_real_kg_drops_known_semgrep() -> None:
    decision = classify(
        {"source_url": "https://github.com/semgrep/semgrep"},
    )
    assert decision.outcome == NoveltyOutcome.DROP
    assert decision.matched_tool_id == "semgrep"


def test_real_kg_continues_genuinely_new() -> None:
    decision = classify(
        {"source_url": "https://github.com/some-fake-org/totally-new-tool-xyz"},
    )
    assert decision.outcome == NoveltyOutcome.CONTINUE


def test_build_kg_index_reads_real_corpus() -> None:
    idx = build_kg_index()
    # Sanity: index has > 50 tools and indexes by github + slug.
    assert len(idx.tools) > 50
    assert "semgrep/semgrep" in idx.by_github
    assert "semgrep" in idx.by_slug
