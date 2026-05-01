"""Tests for ``validator.graduate_papers``.

Coverage:
- id-generation matches the ``<lastname>-<year>-<short-slug>`` convention
- duplicate detection (against arxiv id, doi, title slug)
- schema validation succeeds for at least one synthetic candidate
- the editorial notes block surfaces SAICA-KG failure-mode names in
  snake_case so a future indexer can pick them up
"""

from __future__ import annotations

from pathlib import Path


from validator.graduate_papers import (
    Candidate,
    DedupIndex,
    candidate_to_yaml,
    detect_failure_modes,
    make_paper_id,
    passes_topic_filter,
    run,
    score_candidate,
    validate_payload,
)


# --- Fixtures -------------------------------------------------------------


def _candidate(**overrides) -> Candidate:
    base = dict(
        source="s2:llm-code-failure-taxonomy",
        title="A Taxonomy of Failure Modes in LLM Coding Agents",
        authors=["Jane Q. Researcher", "John X. Coauthor"],
        year=2025,
        abstract=(
            "We collect 500 traces from autonomous coding agents and derive a "
            "taxonomy of failure modes including hallucinations, dependency "
            "blindness, and supply-chain vulnerabilities."
        ),
        tldr=(
            "Empirical taxonomy of 500 coding-agent failures spanning "
            "hallucination, dependency, and supply-chain modes."
        ),
        venue="arXiv.org",
        url="https://arxiv.org/abs/2599.12345",
        doi="10.48550/arXiv.2599.12345",
        arxiv_id="2599.12345",
        semantic_scholar_id="abc123",
        citation_count=42,
    )
    base.update(overrides)
    return Candidate(**base)


# --- ID generation --------------------------------------------------------


def test_make_paper_id_basic_format() -> None:
    pid = make_paper_id(
        ["Mehil B. Shah", "F. Khomh"],
        2026,
        "Characterizing Faults in Agentic AI: A Taxonomy of Types",
    )
    assert pid.startswith("shah-2026-")
    # 4 content words after stopword filter; punctuation stripped.
    assert pid == "shah-2026-characterizing-faults-agentic-ai"


def test_make_paper_id_kebab_case_and_pattern() -> None:
    """The id must satisfy the schema's regex
    ``^[a-z0-9][a-z0-9-]*[a-z0-9]$`` and contain no underscores or
    consecutive dashes.
    """
    import re

    pid = make_paper_id(
        ["Yunseo Lee", "John Youngeun Song"],
        2025,
        "Hallucination by Code Generation LLMs: Taxonomy & Benchmarks!",
    )
    assert re.match(r"^[a-z0-9][a-z0-9-]*[a-z0-9]$", pid)
    assert "_" not in pid
    assert "--" not in pid
    assert pid.startswith("lee-2025-")


def test_make_paper_id_handles_initials_only() -> None:
    pid = make_paper_id(["A. Joshi"], 2026, "XAI for Coding Agent Failures")
    assert pid == "joshi-2026-xai-coding-agent-failures"


def test_make_paper_id_truncates_long_titles() -> None:
    """The slug stays bounded so ids don't get unwieldy."""
    pid = make_paper_id(
        ["Last Author"],
        2025,
        (
            "A Very Long Title That Goes On And On With Many Many "
            "Content Words All Said In One Breath"
        ),
    )
    # 4-word cap + author + year = at most 6 hyphenated segments.
    assert pid.count("-") <= 6


def test_make_paper_id_falls_back_when_no_author() -> None:
    pid = make_paper_id(["et al."], 2024, "Some Untitled Work")
    assert pid.startswith("anon-2024-")


# --- Dedup detection ------------------------------------------------------


def test_dedup_arxiv_match(tmp_path: Path) -> None:
    idx = DedupIndex(arxiv_ids={"2503.13657"})
    c = _candidate(arxiv_id="2503.13657")
    assert idx.is_duplicate(c) == "arxiv_id=2503.13657"


def test_dedup_doi_match() -> None:
    idx = DedupIndex(dois={"10.48550/arxiv.2503.13657"})
    c = _candidate(arxiv_id=None, doi="10.48550/arXiv.2503.13657")
    # case-folded
    assert idx.is_duplicate(c) == "doi=10.48550/arxiv.2503.13657"


def test_dedup_title_match() -> None:
    idx = DedupIndex(titles={"taxonomy-failure-modes-llm-coding-agents"})
    c = _candidate(arxiv_id=None, doi=None)
    assert idx.is_duplicate(c) and idx.is_duplicate(c).startswith("title=")


def test_dedup_no_false_positive() -> None:
    idx = DedupIndex(
        ids={"foo"},
        arxiv_ids={"9999.9999"},
        dois={"10.x/y"},
        titles={"some-other-title"},
    )
    c = _candidate()
    assert idx.is_duplicate(c) is None


def test_dedup_unique_id_disambiguates() -> None:
    idx = DedupIndex(ids={"shah-2026-characterizing-faults"})
    out = idx.unique_id("shah-2026-characterizing-faults")
    assert out == "shah-2026-characterizing-faults-2"
    idx.ids.add(out)
    out2 = idx.unique_id("shah-2026-characterizing-faults")
    assert out2 == "shah-2026-characterizing-faults-3"


def test_dedup_index_loads_existing(tmp_path: Path) -> None:
    """A directory of paper YAMLs feeds the dedup index correctly."""
    p = tmp_path / "papers"
    p.mkdir()
    (p / "fake-2025-thing.yml").write_text(
        "id: fake-2025-thing\n"
        "authors:\n  - Some Author\n"
        "year: 2025\n"
        'title: "Fake Thing About Stuff"\n'
        'arxiv_id: "9000.0001"\n'
        'doi: "10.x/Fake"\n'
    )
    idx = DedupIndex.from_existing(p)
    assert "fake-2025-thing" in idx.ids
    assert "9000.0001" in idx.arxiv_ids
    assert "10.x/fake" in idx.dois  # case-folded
    # title slug stopwords stripped: "fake-thing-stuff"
    assert any("fake" in t for t in idx.titles)


# --- Schema validation ----------------------------------------------------


def test_validate_payload_succeeds_for_synthetic_candidate() -> None:
    c = _candidate()
    pid = make_paper_id(c.authors, c.year, c.title)
    _, payload = candidate_to_yaml(c, pid, ["fabrication", "supply_chain_attack"])
    ok, err = validate_payload(payload)
    assert ok, err


def test_yaml_body_round_trips_through_yaml_safe_load() -> None:
    """The hand-written YAML must parse back to the same payload."""
    import yaml as _yaml

    c = _candidate()
    pid = make_paper_id(c.authors, c.year, c.title)
    body, payload = candidate_to_yaml(c, pid, ["fabrication"])
    parsed = _yaml.safe_load(body)
    # spot-check critical fields
    assert parsed["id"] == payload["id"]
    assert parsed["title"] == payload["title"]
    assert parsed["authors"] == payload["authors"]
    assert parsed["year"] == payload["year"]
    assert parsed["arxiv_id"] == payload["arxiv_id"]
    assert "fabrication" in parsed["notes"]


def test_validate_rejects_missing_authors() -> None:
    c = _candidate(authors=[])
    pid = "x-2025-fake"
    _, payload = candidate_to_yaml(c, pid, [])
    ok, _ = validate_payload(payload)
    assert not ok


# --- Failure-mode detection -----------------------------------------------


def test_detect_failure_modes_picks_obvious_signals() -> None:
    text = (
        "we study hallucinations and supply chain attacks in code llms; "
        "deprecated apis cascade into downstream failures."
    )
    modes = detect_failure_modes(text)
    assert "fabrication" in modes
    assert "supply_chain_attack" in modes
    assert "obsolescence" in modes
    assert "cascading_failure" in modes


def test_detect_failure_modes_returns_empty_for_irrelevant_text() -> None:
    assert detect_failure_modes("a paper about ornithology") == []


def test_notes_block_includes_snake_case_modes() -> None:
    c = _candidate()
    _, payload = candidate_to_yaml(c, "x-2025-fake", ["fabrication", "logic_error"])
    assert "fabrication" in payload["notes"]
    assert "logic_error" in payload["notes"]


# --- Topic filter ---------------------------------------------------------


def test_topic_filter_accepts_coding_agent_paper() -> None:
    c = _candidate()
    assert passes_topic_filter(c)


def test_topic_filter_rejects_pure_geospatial() -> None:
    c = _candidate(
        title="Geospatial Code Generation with Chain-of-Programming",
        abstract="A geospatial code generation framework. Tested on satellite data.",
        tldr="A geospatial code generation framework.",
    )
    assert not passes_topic_filter(c)


def test_topic_filter_rejects_no_authors() -> None:
    c = _candidate(authors=[])
    assert not passes_topic_filter(c)


# --- Scoring sanity -------------------------------------------------------


def test_score_rewards_recency_and_taxonomy_signal() -> None:
    new = _candidate(year=2026, citation_count=5)
    old = _candidate(year=2018, citation_count=5)
    assert score_candidate(new) > score_candidate(old)


def test_score_rewards_citation_count() -> None:
    cited = _candidate(citation_count=500)
    uncited = _candidate(citation_count=0)
    assert score_candidate(cited) > score_candidate(uncited)


# --- End-to-end orchestration (dry mode, isolated tmp dir) -----------------


def test_run_dry_mode_writes_no_files(tmp_path: Path, monkeypatch) -> None:
    """`run(dry=True)` must produce a report and *not* touch papers_dir."""
    papers_dir = tmp_path / "papers"
    papers_dir.mkdir()
    (papers_dir / "seed.yml").write_text(
        'id: seed\nauthors:\n  - X\nyear: 2025\ntitle: "Seed"\n'
    )
    report = tmp_path / "report.md"
    summary = run(
        dry=True,
        limit=5,
        sources=("s2", "elicit"),
        papers_dir=papers_dir,
        report_path=report,
    )
    # Existing seed file must be untouched and no new papers written.
    assert (papers_dir / "seed.yml").exists()
    new_files = [f for f in papers_dir.glob("*.yml") if f.name != "seed.yml"]
    assert new_files == []
    assert report.exists()
    assert "graduate_papers report" in report.read_text()
    assert summary["loaded"] >= 0
    # dry-run still counts accepted candidates in the summary; it just
    # writes no YAML files. Anything between 0 and 5 is fine.
    assert 0 <= summary["accepted"] <= 5


# --- Block-scalar formatting smoke test -----------------------------------


def test_block_scalar_wraps_long_text() -> None:
    from validator.graduate_papers import _block_scalar

    out = _block_scalar("a " * 100)
    assert all(line.startswith("  ") or line == "" for line in out.split("\n"))
    assert max(len(line) for line in out.split("\n")) <= 80
