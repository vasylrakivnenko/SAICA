"""Unit tests for pipeline.nlp.preprocess."""

from __future__ import annotations

import pytest

from pipeline.nlp.preprocess import (
    canonical_url,
    extract_arxiv_ids,
    extract_dois,
    extract_github_urls,
    fuzzy_title_matches,
    keyword_hits,
    relevance_score,
    classify_kind,
)


# ---------------------------------------------------------------------------
# keyword_hits
# ---------------------------------------------------------------------------

def test_keyword_hits_combined_fabrication_and_supply_chain():
    text = "The agent hallucinated a package name from npm (slopsquatting risk)"
    hits = keyword_hits(text)
    assert "fabrication" in hits
    assert "hallucinated" in hits["fabrication"]
    assert "supply_chain_attack" in hits
    assert "slopsquatting" in hits["supply_chain_attack"]


def test_keyword_hits_empty_text():
    assert keyword_hits("") == {}
    assert keyword_hits("totally unrelated text about kittens") == {}


def test_keyword_hits_case_insensitive_and_word_boundary():
    # Exact word "reinvent" matches (case-insensitive); substring "reinventory"
    # must NOT match, since our patterns use word boundaries.
    assert "dependency_blindness" in keyword_hits("Agents REINVENT the wheel")
    assert keyword_hits("reinventory system maintenance") == {}


def test_keyword_hits_multiword_phrase():
    hits = keyword_hits("This is a classic SQL injection attack")
    assert "security_vulnerability" in hits
    # Both 'injection' and 'sql injection' should match.
    matched = hits["security_vulnerability"]
    assert "sql injection" in matched
    assert "injection" in matched


def test_keyword_hits_whitespace_runs_in_phrase():
    text = "context\n\ndrift observed across long conversations"
    hits = keyword_hits(text)
    assert "context_pollution" in hits


# ---------------------------------------------------------------------------
# extract_github_urls
# ---------------------------------------------------------------------------

def test_extract_github_urls_basic():
    text = "see https://github.com/anthropic/claude-agent-sdk for details"
    assert extract_github_urls(text) == [
        "https://github.com/anthropic/claude-agent-sdk"
    ]


def test_extract_github_urls_strips_git_suffix_and_dedupes():
    text = (
        "clone git from https://github.com/openai/codex.git and "
        "see https://github.com/openai/codex in docs, plus "
        "https://www.github.com/openai/codex too"
    )
    got = extract_github_urls(text)
    assert got == ["https://github.com/openai/codex"]


def test_extract_github_urls_ignores_non_github():
    text = "visit https://gitlab.com/foo/bar or https://bitbucket.org/foo/bar"
    assert extract_github_urls(text) == []


def test_extract_github_urls_multiple_distinct():
    text = (
        "repos: https://github.com/a/one and https://github.com/b/two "
        "and https://github.com/c/three"
    )
    assert extract_github_urls(text) == [
        "https://github.com/a/one",
        "https://github.com/b/two",
        "https://github.com/c/three",
    ]


def test_extract_github_urls_empty():
    assert extract_github_urls("") == []
    assert extract_github_urls("no urls here") == []


# ---------------------------------------------------------------------------
# relevance_score
# ---------------------------------------------------------------------------

def test_relevance_score_low_for_empty_row():
    assert relevance_score({"title": "", "snippet": "", "url": ""}) == 0.0


def test_relevance_score_cap_on_keywords():
    # Force many failure modes hit so the 0.5 cap applies.
    snippet = (
        "hallucination, slopsquatting, deprecated, reinvent, "
        "sql injection, scope creep, context drift, silent fail"
    )
    score = relevance_score({"title": "t", "snippet": snippet, "url": ""})
    # 8 failure modes → would be 1.2, capped at 0.5.
    assert score == pytest.approx(0.5, abs=1e-6)


def test_relevance_score_github_and_keyword():
    row = {
        "title": "slopsquatting tool",
        "snippet": "repo at https://github.com/example/sloptrap detects hallucination",
        "url": "https://github.com/example/sloptrap",
        "source": "github",
    }
    score = relevance_score(row)
    # 2 failure modes (fabrication, supply_chain_attack) → 0.3, +0.2 github = 0.5
    assert score >= 0.45


def test_relevance_score_academic_source_with_arxiv():
    row = {
        "title": "On Library Evolution in LLM Code",
        "snippet": "We study deprecated apis. arXiv:2403.12345",
        "url": "https://arxiv.org/abs/2403.12345",
        "source": "elicit",
    }
    score = relevance_score(row)
    # 1 fm (obsolescence) 0.15 + arxiv 0.2 + elicit 0.1 = 0.45
    assert 0.4 <= score <= 0.6


def test_relevance_score_high_signal_org_bonus():
    row = {
        "title": "Anthropic publishes slopsquatting analysis",
        "snippet": "hallucination in package names",
        "url": "",
        "source": "perplexity",
    }
    # 2 fms (fabrication, supply_chain_attack) = 0.3 + anthropic = 0.1 -> 0.4
    score = relevance_score(row)
    assert score >= 0.35
    assert score <= 1.0


# ---------------------------------------------------------------------------
# canonical_url
# ---------------------------------------------------------------------------

def test_canonical_url_lowercases_host_and_strips_trailing_slash():
    assert (
        canonical_url("HTTPS://GitHub.com/Anthropics/Claude/")
        == "https://github.com/Anthropics/Claude"
    )


def test_canonical_url_strips_utm_params():
    assert (
        canonical_url("https://example.com/post?utm_source=tw&id=5&utm_medium=x")
        == "https://example.com/post?id=5"
    )


def test_canonical_url_strips_fbclid_and_ref():
    url = "https://example.com/x?fbclid=abc&ref_src=foo&keep=1"
    assert canonical_url(url) == "https://example.com/x?keep=1"


def test_canonical_url_keeps_root_slash():
    # We don't want to strip the *only* slash (path='/').
    assert canonical_url("https://example.com/") == "https://example.com"


def test_canonical_url_empty():
    assert canonical_url("") == ""


def test_canonical_url_drops_default_port():
    assert canonical_url("https://example.com:443/a/b") == "https://example.com/a/b"


# ---------------------------------------------------------------------------
# fuzzy_title_matches
# ---------------------------------------------------------------------------

def test_fuzzy_title_matches_finds_near_duplicate():
    candidates = [
        "Detecting Hallucinated Package Names in LLM-generated Code",
        "A Study of Deprecated APIs in Python Libraries",
    ]
    got = fuzzy_title_matches(
        "Detecting Hallucinated Package Names in LLM Generated Code",
        candidates,
    )
    assert candidates[0] in got
    assert candidates[1] not in got


def test_fuzzy_title_matches_empty_inputs():
    assert fuzzy_title_matches("", ["x"]) == []
    assert fuzzy_title_matches("x", []) == []
    assert fuzzy_title_matches("x", [None, ""]) == []


def test_fuzzy_title_matches_threshold():
    # Identical titles should match at any reasonable threshold.
    got = fuzzy_title_matches("hello world", ["HELLO WORLD"], threshold=92)
    assert got == ["HELLO WORLD"]


def test_fuzzy_title_matches_rejects_unrelated():
    got = fuzzy_title_matches(
        "Slopsquatting in npm",
        ["Building a Postgres migration tool"],
    )
    assert got == []


# ---------------------------------------------------------------------------
# extras: extract_arxiv_ids / extract_dois / classify_kind (light coverage)
# ---------------------------------------------------------------------------

def test_extract_arxiv_ids_new_and_old():
    text = "see arXiv:2403.12345v2 and cs.CL/0608032 for details"
    ids = extract_arxiv_ids(text)
    assert "2403.12345" in ids
    assert "cs.CL/0608032" in ids


def test_extract_dois():
    text = "doi: 10.1145/3597503.3639110 and 10.1109/ICSE.2024.00001."
    dois = extract_dois(text)
    assert "10.1145/3597503.3639110" in dois
    # Trailing period stripped.
    assert "10.1109/ICSE.2024.00001" in dois


def test_classify_kind_tool_from_github():
    row = {
        "title": "Awesome CLI for AI agents",
        "snippet": "framework at https://github.com/foo/bar",
        "url": "https://github.com/foo/bar",
        "source": "github",
    }
    assert classify_kind(row) == "tool"


def test_classify_kind_paper_from_arxiv():
    row = {
        "title": "On slopsquatting",
        "snippet": "arXiv:2403.12345",
        "url": "https://arxiv.org/abs/2403.12345",
        "source": "semantic_scholar",
    }
    assert classify_kind(row) == "paper"
