"""Tests for the arXiv recent-submissions scraper.

All tests are network-free: the Atom XML fixture lives at
``fixtures/arxiv_sample.xml`` and the fetcher is exercised through the
on-disk cache (``--no-network`` mode) plus a tiny ``papers/`` shim.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from pipeline.sources import arxiv_recent as ar
from validator import screen_arxiv as sa

FIXTURES = Path(__file__).parent / "fixtures"
SAMPLE_XML = (FIXTURES / "arxiv_sample.xml").read_text(encoding="utf-8")


# ---------------------------------------------------------------------------
# parse_atom
# ---------------------------------------------------------------------------

def test_parse_atom_extracts_all_entries() -> None:
    items = ar.parse_atom(SAMPLE_XML)
    assert len(items) == 4
    by_id = {it["arxiv_id"]: it for it in items}
    # The shah-2026 entry should land with the bare id (no version suffix).
    assert "2603.06847" in by_id
    shah = by_id["2603.06847"]
    assert shah["primary_category"] == "cs.SE"
    assert shah["first_published"] == "2026-03-06"
    assert shah["authors"][0] == "Mehil B. Shah"
    assert "agentic" in shah["abstract"].lower()


def test_parse_atom_handles_multi_category_entry() -> None:
    items = ar.parse_atom(SAMPLE_XML)
    by_id = {it["arxiv_id"]: it for it in items}
    guard = by_id["2604.99001"]
    assert "cs.SE" in guard["categories"]
    assert "cs.AI" in guard["categories"]
    assert guard["primary_category"] == "cs.SE"


def test_parse_atom_strips_version_suffix() -> None:
    # Every <id> in the fixture ends in vN; bare ids must come back clean.
    for it in ar.parse_atom(SAMPLE_XML):
        assert "v" not in it["arxiv_id"]
        assert it["arxiv_id"].count(".") == 1


def test_parse_atom_empty_returns_empty() -> None:
    assert ar.parse_atom("") == []


# ---------------------------------------------------------------------------
# score_relevance
# ---------------------------------------------------------------------------

def test_score_relevance_empty_returns_zero() -> None:
    assert ar.score_relevance("") == 0.0
    assert ar.score_relevance(None) == 0.0  # type: ignore[arg-type]


def test_score_relevance_off_topic_clamps_to_zero() -> None:
    text = (
        "A new diffusion model for image generation in fashion design, "
        "with NFT and blockchain crypto trading marketplace integration, "
        "applied to medical imaging and protein folding."
    )
    assert ar.score_relevance(text) == 0.0


def test_score_relevance_high_for_canonical_supervision_abstract() -> None:
    text = (
        "We propose guardrails for LLM coding agents that detect scope "
        "creep and fabrication in Claude Code traces — a study of failure "
        "modes in agentic AI."
    )
    score = ar.score_relevance(text)
    assert score >= ar.RELEVANCE_THRESHOLD
    assert score == 1.0  # well over the ceiling


def test_score_relevance_at_threshold() -> None:
    # "supervision" alone (weight 4) -> 0.4 -> exactly threshold.
    text = "A supervision toolkit."
    score = ar.score_relevance(text)
    assert score == pytest.approx(0.4, rel=1e-6)
    assert score >= ar.RELEVANCE_THRESHOLD


def test_score_relevance_just_below_threshold_is_filtered() -> None:
    # "lint"(1) + "monitor"(1) + "tracing"(1) = 3 -> 0.3 < 0.4
    text = "A lightweight lint, monitor, tracing helper."
    score = ar.score_relevance(text)
    assert score < ar.RELEVANCE_THRESHOLD
    assert score == pytest.approx(0.3, rel=1e-6)


# ---------------------------------------------------------------------------
# infer_failure_modes
# ---------------------------------------------------------------------------

def test_infer_failure_modes_picks_up_scope_creep_and_fabrication() -> None:
    text = (
        "We detect scope creep on edits, fabrication of nonexistent APIs, "
        "and prompt injection attacks against LLM coding agents."
    )
    fms = ar.infer_failure_modes(text)
    assert "scope_creep" in fms
    assert "fabrication" in fms
    assert "context_pollution" in fms


def test_infer_failure_modes_returns_sorted_unique() -> None:
    text = "supply chain slopsquat and supply chain again, slopsquat."
    fms = ar.infer_failure_modes(text)
    assert fms == sorted(fms)
    assert fms.count("supply_chain_attack") == 1


def test_infer_failure_modes_empty_text_returns_empty_list() -> None:
    assert ar.infer_failure_modes("") == []


# ---------------------------------------------------------------------------
# suggested_id
# ---------------------------------------------------------------------------

def test_suggested_id_matches_shah_2026_convention() -> None:
    sid = ar.suggested_id(
        ["Mehil B. Shah", "Mohammad Mehdi Morovati"],
        2026,
        "Characterizing Faults in Agentic AI: A Taxonomy of Types, Symptoms, and Root Causes",
    )
    # Mirrors data/papers/shah-2026-characterizing-faults.yml
    assert sid.startswith("shah-2026-")
    assert "characterizing" in sid
    # 2..4 slug tokens
    slug = sid.split("shah-2026-", 1)[1]
    assert 1 < len(slug.split("-")) <= 4


def test_suggested_id_strips_diacritics_and_handles_comma_form() -> None:
    sid = ar.suggested_id(["Renée García, Maria"], 2025, "A Novel Framework for Code Generation")
    # Comma form: surname is "García" -> diacritic-stripped to "garcia".
    assert sid.startswith("garcia-2025-")
    assert "code" in sid
    assert "generation" in sid


def test_suggested_id_drops_jr_suffix() -> None:
    sid = ar.suggested_id(["Robert Smith Jr."], 2026, "Empirical Study of LLM Agents")
    assert sid.startswith("smith-2026-")


def test_suggested_id_empty_authors_falls_back_to_unknown() -> None:
    sid = ar.suggested_id([], 2026, "Some Title Here")
    assert sid.startswith("unknown-2026-")


# ---------------------------------------------------------------------------
# match_against_kg + load_kg_arxiv_ids
# ---------------------------------------------------------------------------

def test_load_kg_arxiv_ids_from_fixture_papers_dir(tmp_path: Path) -> None:
    pdir = tmp_path / "papers"
    pdir.mkdir()
    (pdir / "shah-2026-characterizing-faults.yml").write_text(
        "id: shah-2026-characterizing-faults\narxiv_id: \"2603.06847\"\n",
        encoding="utf-8",
    )
    (pdir / "kumar-2026-agentforge.yml").write_text(
        "id: kumar-2026-agentforge\nurl: https://arxiv.org/abs/2604.13120\n",
        encoding="utf-8",
    )
    (pdir / "no-arxiv.yml").write_text(
        "id: no-arxiv\nurl: https://example.com/paper\n",
        encoding="utf-8",
    )
    ids = ar.load_kg_arxiv_ids(papers_dir=pdir)
    assert ids["2603.06847"] == "shah-2026-characterizing-faults"
    assert ids["2604.13120"] == "kumar-2026-agentforge"
    assert "no-arxiv" not in ids.values()


def test_match_against_kg_routes_known_ids() -> None:
    candidates = [
        {
            "arxiv_id": "2603.06847",
            "title": "Characterizing Faults",
            "first_published": "2026-03-06",
        },
        {
            "arxiv_id": "2604.99999",
            "title": "Brand New Paper",
            "first_published": "2026-04-25",
        },
    ]
    kg = {"2603.06847": "shah-2026-characterizing-faults"}
    matched, new = ar.match_against_kg(candidates, kg)
    assert len(matched) == 1
    assert matched[0]["paper_id"] == "shah-2026-characterizing-faults"
    assert matched[0]["arxiv_id"] == "2603.06847"
    assert len(new) == 1
    assert new[0]["arxiv_id"] == "2604.99999"


# ---------------------------------------------------------------------------
# fetch_recent — uses on-disk cache, no network
# ---------------------------------------------------------------------------

def test_fetch_recent_uses_cache(tmp_path: Path) -> None:
    cache_dir = tmp_path / "cache"
    cache_dir.mkdir()
    today = "2026-04-30"
    (cache_dir / f"{today}__cs.SE__lb30.xml").write_text(SAMPLE_XML, encoding="utf-8")
    items = ar.fetch_recent(
        category="cs.SE",
        lookback_days=30,
        today_iso=today,
        use_network=False,
        cache_dir=cache_dir,
    )
    assert len(items) == 4
    assert any(it["arxiv_id"] == "2603.06847" for it in items)


def test_fetch_recent_no_cache_no_network_returns_empty(tmp_path: Path) -> None:
    items = ar.fetch_recent(
        category="cs.AI",
        lookback_days=30,
        today_iso="2026-04-30",
        use_network=False,
        cache_dir=tmp_path / "empty",
    )
    assert items == []


# ---------------------------------------------------------------------------
# End-to-end orchestrator (network-free, fixture-fed)
# ---------------------------------------------------------------------------

def _seed_cache(cache_dir: Path, today: str, lookback_days: int, categories: list[str]) -> None:
    """Seed every category's cache slot with the same fixture XML."""
    cache_dir.mkdir(parents=True, exist_ok=True)
    for cat in categories:
        (cache_dir / f"{today}__{cat}__lb{lookback_days}.xml").write_text(
            SAMPLE_XML, encoding="utf-8"
        )


def test_end_to_end_orchestrator_offline(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    cache_dir = tmp_path / "cache" / "arxiv"
    today = "2026-04-30"
    categories = ["cs.SE", "cs.AI", "cs.LG"]
    _seed_cache(cache_dir, today, 30, categories)

    # Seed a tiny KG papers/ dir holding just the shah-2026 entry, so the
    # orchestrator routes it to matched_in_kg.
    pdir = tmp_path / "data" / "papers"
    pdir.mkdir(parents=True)
    (pdir / "shah-2026-characterizing-faults.yml").write_text(
        "id: shah-2026-characterizing-faults\narxiv_id: \"2603.06847\"\n",
        encoding="utf-8",
    )

    monkeypatch.setattr(ar, "CACHE_DIR", cache_dir)
    monkeypatch.setattr(ar, "PAPERS_DIR", pdir)
    monkeypatch.setattr(sa, "DATA_DIR", tmp_path / "data")
    monkeypatch.setattr(sa, "RESEARCH_DIR", tmp_path / "research")
    monkeypatch.setattr(sa, "ARXIV_JSON", tmp_path / "data" / "arxiv_candidates.json")

    # Pin "today" so the markdown filename is predictable.
    import datetime as _dt

    class _FixedDate(_dt.date):
        @classmethod
        def today(cls) -> _dt.date:  # type: ignore[override]
            return _dt.date(2026, 4, 30)

    monkeypatch.setattr(_dt, "date", _FixedDate)

    rc = sa.main(["--no-network", "--lookback-days", "30",
                  "--categories", ",".join(categories)])
    assert rc == 0

    snap_path = tmp_path / "data" / "arxiv_candidates.json"
    assert snap_path.exists()
    snap = json.loads(snap_path.read_text(encoding="utf-8"))

    # Schema sanity.
    assert set(snap.keys()) >= {
        "scraped_at",
        "categories",
        "lookback_days",
        "matched_in_kg",
        "new_candidates",
    }
    assert snap["lookback_days"] == 30
    assert snap["categories"] == categories

    # shah-2026 entry must route to matched_in_kg, not new_candidates.
    matched_pids = {m["paper_id"] for m in snap["matched_in_kg"]}
    assert "shah-2026-characterizing-faults" in matched_pids
    new_ids = {c["arxiv_id"] for c in snap["new_candidates"]}
    assert "2603.06847" not in new_ids

    # The high-relevance "guardrails" entry must appear as a new candidate.
    assert "2604.99001" in new_ids
    guard = next(c for c in snap["new_candidates"] if c["arxiv_id"] == "2604.99001")
    assert guard["relevance_score"] >= ar.RELEVANCE_THRESHOLD
    assert any(
        fm in guard["suggested_failure_modes"]
        for fm in ("scope_creep", "fabrication", "context_pollution")
    )
    # Suggested SAICA id mirrors the data/papers/<id>.yml convention.
    assert guard["suggested_id"].startswith("doe-2026-")

    # Off-topic image-generation entry must NOT appear (relevance below cutoff).
    assert "2604.99002" not in new_ids
    # Lightweight static-analysis entry: lint+monitor+tracing = 0.3 < 0.4.
    assert "2604.99003" not in new_ids

    # Markdown report exists and names the canonical example.
    md_path = tmp_path / "research" / "arxiv_candidates_2026-04-30.md"
    assert md_path.exists()
    md = md_path.read_text(encoding="utf-8")
    assert "shah-2026-characterizing-faults" in md
    assert "2603.06847" in md
    assert "Guardrails" in md or "guardrails" in md.lower()


def test_end_to_end_dry_does_not_write(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    cache_dir = tmp_path / "cache" / "arxiv"
    today = "2026-04-30"
    categories = ["cs.SE"]
    _seed_cache(cache_dir, today, 30, categories)

    pdir = tmp_path / "data" / "papers"
    pdir.mkdir(parents=True)

    monkeypatch.setattr(ar, "CACHE_DIR", cache_dir)
    monkeypatch.setattr(ar, "PAPERS_DIR", pdir)
    monkeypatch.setattr(sa, "DATA_DIR", tmp_path / "data")
    monkeypatch.setattr(sa, "RESEARCH_DIR", tmp_path / "research")
    monkeypatch.setattr(sa, "ARXIV_JSON", tmp_path / "data" / "arxiv_candidates.json")

    import datetime as _dt

    class _FixedDate(_dt.date):
        @classmethod
        def today(cls) -> _dt.date:  # type: ignore[override]
            return _dt.date(2026, 4, 30)

    monkeypatch.setattr(_dt, "date", _FixedDate)

    rc = sa.main([
        "--dry", "--no-network", "--lookback-days", "30",
        "--categories", "cs.SE",
    ])
    assert rc == 0
    assert not (tmp_path / "data" / "arxiv_candidates.json").exists()
    assert not (tmp_path / "research" / "arxiv_candidates_2026-04-30.md").exists()


def test_render_markdown_handles_empty_candidates() -> None:
    md = sa.render_markdown(
        matched=[], new=[], today_iso="2026-04-30",
        categories=["cs.SE"], lookback_days=30,
    )
    assert "2026-04-30" in md
    assert "No new arXiv submissions" in md


def test_polite_scraper_session_has_user_agent_and_interval() -> None:
    assert "SAICA-KG-Arxiv-Bot" in ar._SESSION.headers["User-Agent"]
    assert ar._SESSION._min_interval >= 2.0
