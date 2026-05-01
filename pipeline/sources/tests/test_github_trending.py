"""Tests for the github.com/trending scraper.

All tests are network-free: HTML fixtures are stored under
``fixtures/trending_sample.html`` and the trending fetcher is exercised
through the on-disk cache (``--no-network`` mode).
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from pipeline.sources import github_trending as gt
from validator import screen_trending as st

FIXTURES = Path(__file__).parent / "fixtures"
SAMPLE_HTML = (FIXTURES / "trending_sample.html").read_text(encoding="utf-8")


# ---------------------------------------------------------------------------
# normalize_repository_url
# ---------------------------------------------------------------------------

@pytest.mark.parametrize(
    "raw, expected",
    [
        ("https://github.com/owner/repo", "https://github.com/owner/repo"),
        ("https://github.com/owner/repo/", "https://github.com/owner/repo"),
        ("https://GitHub.com/owner/repo.git", "https://github.com/owner/repo"),
        ("https://github.com/owner/repo.git/", "https://github.com/owner/repo"),
        ("https://github.com/owner/repo?utm_source=x", "https://github.com/owner/repo"),
        ("https://github.com/owner/repo#readme", "https://github.com/owner/repo"),
        ("HTTPS://GITHUB.COM/Owner/Repo/", "https://github.com/Owner/Repo"),
        ("", ""),
    ],
)
def test_normalize_repository_url(raw: str, expected: str) -> None:
    assert gt.normalize_repository_url(raw) == expected


# ---------------------------------------------------------------------------
# score_relevance — boundary checks
# ---------------------------------------------------------------------------

def test_score_relevance_empty_returns_zero() -> None:
    assert gt.score_relevance("") == 0.0
    assert gt.score_relevance(None) == 0.0  # type: ignore[arg-type]


def test_score_relevance_off_topic_clamps_to_zero() -> None:
    text = (
        "A music generator and image generator for fashion designers, "
        "with a blockchain crypto trading and NFT homework tutorial."
    )
    # All anti-signals — sum is negative, clamps to 0.
    assert gt.score_relevance(text) == 0.0


def test_score_relevance_high_for_canonical_skills_readme() -> None:
    text = (
        "I built these skills as a way to fix common failure modes I see "
        "with Claude Code, Codex, and other coding agents. Helpful for "
        "scope creep and hallucination."
    )
    score = gt.score_relevance(text)
    # claude code(3) + codex(2) + coding agent(4) + failure modes(5) +
    # scope creep(4) + hallucinat(3) = 21 -> 1.0 (clamped)
    assert score >= gt.RELEVANCE_THRESHOLD
    assert score == 1.0


def test_score_relevance_at_threshold() -> None:
    # Single "supervision" hit (weight 4) -> 0.4 -> exactly threshold.
    text = "A supervision toolkit."
    score = gt.score_relevance(text)
    assert score == pytest.approx(0.4, rel=1e-6)
    assert score >= gt.RELEVANCE_THRESHOLD


def test_score_relevance_just_below_threshold_is_filtered() -> None:
    # "lint"(1) + "monitor"(1) + "tracing"(1) = 3 -> 0.3 < 0.4
    text = "A lightweight lint, monitor, tracing helper."
    score = gt.score_relevance(text)
    assert score < gt.RELEVANCE_THRESHOLD
    assert score == pytest.approx(0.3, rel=1e-6)


# ---------------------------------------------------------------------------
# infer_failure_modes — README-driven, reuses kg.FM_KEYWORDS
# ---------------------------------------------------------------------------

def test_infer_failure_modes_picks_up_scope_creep_and_fabrication() -> None:
    readme = (
        "These skills fix common failure modes I see with Claude Code: "
        "scope creep on edits, fabrication of nonexistent APIs, and "
        "context pollution from prompt injection."
    )
    fms = gt.infer_failure_modes(readme)
    assert "scope_creep" in fms
    assert "fabrication" in fms
    assert "context_pollution" in fms


def test_infer_failure_modes_returns_sorted_unique() -> None:
    readme = "supply chain slopsquat and supply chain again, slopsquat."
    fms = gt.infer_failure_modes(readme)
    assert fms == sorted(fms)
    assert fms.count("supply_chain_attack") == 1


def test_infer_failure_modes_empty_text_returns_empty_list() -> None:
    assert gt.infer_failure_modes("") == []


# ---------------------------------------------------------------------------
# parse_trending_html
# ---------------------------------------------------------------------------

def test_parse_trending_html_extracts_three_repos() -> None:
    items = gt.parse_trending_html(SAMPLE_HTML)
    assert len(items) == 3
    by_full = {it["full_name"]: it for it in items}
    assert "mattpocock/skills" in by_full
    skills = by_full["mattpocock/skills"]
    assert skills["repository_url"] == "https://github.com/mattpocock/skills"
    assert skills["stars_total"] == 49231
    assert skills["language"] == "Markdown"
    assert "Claude Code" in skills["description"]


def test_parse_trending_html_regex_fallback_matches_bs4() -> None:
    bs4_items = gt._parse_with_bs4(SAMPLE_HTML)
    regex_items = gt._parse_with_regex(SAMPLE_HTML)
    bs4_names = {i["full_name"] for i in bs4_items}
    regex_names = {i["full_name"] for i in regex_items}
    # Regex parser must catch at least the same repos.
    assert bs4_names == regex_names


# ---------------------------------------------------------------------------
# fetch_trending_page — uses on-disk cache, no network
# ---------------------------------------------------------------------------

def test_fetch_trending_page_uses_cache(tmp_path: Path) -> None:
    cache_dir = tmp_path / "cache"
    cache_dir.mkdir()
    today = "2026-04-23"
    # Mirror the cache key used by fetch_trending_page.
    (cache_dir / f"{today}__all__daily.html").write_text(SAMPLE_HTML, encoding="utf-8")
    items = gt.fetch_trending_page(
        language=None,
        since="daily",
        today_iso=today,
        use_network=False,
        cache_dir=cache_dir,
    )
    assert len(items) == 3
    assert any(it["full_name"] == "mattpocock/skills" for it in items)


def test_fetch_trending_page_no_cache_no_network_returns_empty(tmp_path: Path) -> None:
    items = gt.fetch_trending_page(
        language="rust",
        since="weekly",
        today_iso="2026-04-23",
        use_network=False,
        cache_dir=tmp_path / "empty",
    )
    assert items == []


# ---------------------------------------------------------------------------
# End-to-end orchestrator integration (network-free, fixture-fed)
# ---------------------------------------------------------------------------

def _seed_cache(cache_dir: Path, today: str) -> None:
    """Seed every (lang, since) cache entry with the same fixture HTML."""
    cache_dir.mkdir(parents=True, exist_ok=True)
    for lang, since in gt.iter_default_pages():
        lang_label = lang or "all"
        (cache_dir / f"{today}__{lang_label}__{since}.html").write_text(
            SAMPLE_HTML, encoding="utf-8"
        )


def test_end_to_end_orchestrator_offline(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    cache_dir = tmp_path / "cache" / "trending"
    today = "2026-04-23"
    _seed_cache(cache_dir, today)

    # Redirect the module-level CACHE_DIR so fetch_trending_page reads from
    # our seeded fixture cache.
    monkeypatch.setattr(gt, "CACHE_DIR", cache_dir)
    # No-network mode also short-circuits fetch_readme to the description.
    monkeypatch.setattr(st, "DATA_DIR", tmp_path / "data")
    monkeypatch.setattr(st, "RESEARCH_DIR", tmp_path / "research")
    monkeypatch.setattr(st, "TRENDING_JSON", tmp_path / "data" / "trending.json")

    # Pin "today" so the markdown filename is predictable.
    import datetime as _dt

    class _FixedDate(_dt.date):
        @classmethod
        def today(cls) -> _dt.date:  # type: ignore[override]
            return _dt.date(2026, 4, 23)

    monkeypatch.setattr(_dt, "date", _FixedDate)

    rc = st.main(["--no-network"])
    assert rc == 0

    snap_path = tmp_path / "data" / "trending.json"
    assert snap_path.exists()
    snap = json.loads(snap_path.read_text(encoding="utf-8"))

    # Schema sanity.
    assert set(snap.keys()) >= {
        "scraped_at",
        "sources",
        "trending_repository_urls",
        "matched_in_kg",
        "new_candidates",
    }
    # promptfoo is in the KG -> matched_in_kg.
    matched_ids = {m["tool_id"] for m in snap["matched_in_kg"]}
    assert "promptfoo" in matched_ids
    # mattpocock/skills is NOT in the KG and its description is highly
    # relevant -> should appear as a new candidate.
    cand_urls = {c["repository_url"] for c in snap["new_candidates"]}
    assert "https://github.com/mattpocock/skills" in cand_urls

    # The skills candidate must include at least one of the targeted FMs.
    skills = next(
        c for c in snap["new_candidates"]
        if c["repository_url"] == "https://github.com/mattpocock/skills"
    )
    assert skills["relevance_score"] >= gt.RELEVANCE_THRESHOLD
    assert any(
        fm in skills["suggested_failure_modes"]
        for fm in ("scope_creep", "fabrication", "context_pollution")
    )

    # The off-topic blockchain repo must NOT appear (relevance below cutoff).
    assert "https://github.com/owner3/cool-game-engine" not in cand_urls

    # Markdown report exists and names the canonical example.
    md_path = tmp_path / "research" / "trending_candidates_2026-04-23.md"
    assert md_path.exists()
    md = md_path.read_text(encoding="utf-8")
    assert "skills" in md
    assert "Claude Code" in md or "claude code" in md.lower()


def test_build_url_to_tool_id_normalizes() -> None:
    fake_index = {
        "foo": {"repository_url": "https://github.com/Foo/Bar.git/"},
        "baz": {"repository_url": "HTTPS://github.com/baz/qux"},
        "no_url": {"name": "no url"},
    }
    rev = st.build_url_to_tool_id(fake_index)
    assert rev["https://github.com/Foo/Bar"] == "foo"
    assert rev["https://github.com/baz/qux"] == "baz"
    assert "no_url" not in rev.values() or "no_url" not in rev


def test_render_markdown_handles_empty_candidates() -> None:
    md = st.render_markdown([], "2026-04-23")
    assert "2026-04-23" in md
    assert "No new repositories" in md


def test_readme_excerpt_prefers_relevant_paragraph() -> None:
    text = (
        "An overview paragraph with no signal words.\n\n"
        "This second paragraph mentions claude code and scope creep "
        "and is therefore the relevant one."
    )
    excerpt = gt.readme_excerpt(text, max_chars=200)
    assert "claude code" in excerpt.lower()
