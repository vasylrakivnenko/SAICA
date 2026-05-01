"""Unit tests for pipeline.nlp.preprocess."""

from __future__ import annotations

import pytest

from pipeline.nlp.preprocess import (
    LOW_RELEVANCE_THRESHOLD,
    PROMOTION_THRESHOLD,
    canonical_url,
    classify_kind,
    extract_arxiv_ids,
    extract_dois,
    extract_github_urls,
    fuzzy_title_matches,
    keyword_hits,
    relevance_score,
    tool_shape_hits,
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
    # Force many failure modes hit so the 0.4 failure-mode cap applies.
    snippet = (
        "hallucination, slopsquatting, deprecated, reinvent, "
        "sql injection, scope creep, context drift, silent fail"
    )
    score = relevance_score({"title": "t", "snippet": snippet, "url": ""})
    # 8 failure modes → would be 0.8, capped at 0.4.
    # Length of title+snippet >= 80 chars → +0.05.
    # No tool-shape / github / arxiv / github-source contributions.
    assert score == pytest.approx(0.45, abs=1e-6)


def test_relevance_score_github_and_keyword():
    row = {
        "title": "slopsquatting tool",
        "snippet": "repo at https://github.com/example/sloptrap detects hallucination",
        "url": "https://github.com/example/sloptrap",
        "source": "github",
    }
    score = relevance_score(row)
    # 2 failure modes → 0.2, +0.25 github entity, +0.05 github source,
    # +0.05 length ≥ 80. Tool-shape: none. Expect ~0.55.
    assert score >= 0.45


def test_relevance_score_academic_source_with_arxiv():
    row = {
        "title": "On Library Evolution in LLM Code: a comprehensive study",
        "snippet": "We study deprecated apis across ecosystems. arXiv:2403.12345",
        "url": "https://arxiv.org/abs/2403.12345",
        "source": "elicit",
    }
    score = relevance_score(row)
    # 1 fm (obsolescence) 0.1 + arxiv/doi 0.1 + length 0.05 = 0.25
    assert 0.2 <= score <= 0.4


def test_relevance_score_paper_signal_without_github():
    row = {
        "title": "Anthropic publishes slopsquatting analysis on hallucinated imports",
        "snippet": "hallucination in package names leads to typosquatting attacks",
        "url": "",
        "source": "perplexity",
    }
    # 2 fms (fabrication, supply_chain_attack) = 0.2 + length 0.05 = 0.25
    score = relevance_score(row)
    assert score >= 0.2
    assert score <= 1.0


# ---------------------------------------------------------------------------
# Listicle rescue / drop behavior (borderline-candidate policy)
# ---------------------------------------------------------------------------


def test_relevance_score_listicle_without_github_is_dropped():
    """A Perplexity listicle with no entity signal must fall below the
    promotion threshold so we don't Kimi-extract it."""
    row = {
        "title": "Top 10 AI Coding Agents 2026",
        "snippet": "A ranked list of popular AI coding agents for 2026.",
        "url": "https://example.com/blog/top-10-ai-coding-agents-2026",
        "source": "perplexity",
    }
    score = relevance_score(row)
    assert score < PROMOTION_THRESHOLD


def test_relevance_score_listicle_with_github_url_is_rescued():
    """Same listicle title but with a github repo URL present clears the
    promotion threshold thanks to the entity signal."""
    row = {
        "title": "Top 10 AI Coding Agents 2026",
        "snippet": (
            "A ranked list of AI coding agents. Source: "
            "https://github.com/owner/repo"
        ),
        "url": "https://github.com/owner/repo",
        "source": "perplexity",
    }
    score = relevance_score(row)
    assert score >= PROMOTION_THRESHOLD


def test_relevance_score_outlines_tool_with_github_clears_high_bar():
    """A domain-relevant tool page with a github URL should score well above
    the low bar — ~0.4 or more."""
    row = {
        "title": "Outlines: constrained decoding framework for LLMs",
        "snippet": (
            "Outlines is a structured output library with tool calling and "
            "guardrails for safer LLM generation. https://github.com/outlines-dev/outlines"
        ),
        "url": "https://github.com/outlines-dev/outlines",
        "source": "github",
    }
    score = relevance_score(row)
    assert score >= 0.4


# ---------------------------------------------------------------------------
# tool_shape_hits + keyword coverage spot checks
# ---------------------------------------------------------------------------


def test_tool_shape_hits_distinct_phrases():
    text = (
        "An MCP server providing guardrails, sandboxed execution, and "
        "observability via tracing and telemetry for agent orchestration."
    )
    hits = tool_shape_hits(text)
    # Distinct TOOL_SHAPE_SIGNALS phrases that should match this text.
    for expected in (
        "mcp server",
        "guardrails",
        "sandboxed",
        "observability",
        "tracing",
        "telemetry",
        "agent orchestration",
    ):
        assert expected in hits, f"expected {expected!r} in tool_shape_hits"


def test_tool_shape_hits_empty_when_absent():
    assert tool_shape_hits("") == []
    assert tool_shape_hits("unrelated text about kittens") == []


def test_keyword_hits_slopsquatting_supply_chain():
    """Per brief: 'slopsquatting' must still hit supply_chain_attack."""
    hits = keyword_hits("the slopsquatting risk is elevated in 2026")
    assert "supply_chain_attack" in hits
    assert "slopsquatting" in hits["supply_chain_attack"]


def test_keyword_hits_hallucination_fabrication():
    """Per brief: 'hallucination' must still hit fabrication."""
    hits = keyword_hits("this agent exhibits persistent hallucination")
    assert "fabrication" in hits
    assert "hallucination" in hits["fabrication"]


def test_keyword_hits_reinvent_dependency_blindness():
    """Per brief: 'reinvent' must still hit dependency_blindness."""
    hits = keyword_hits("LLMs tend to reinvent existing utilities")
    assert "dependency_blindness" in hits
    assert "reinvent" in hits["dependency_blindness"]


def test_promotion_and_low_relevance_thresholds_are_sane():
    """Thresholds must form a valid band so borderline rows have a home."""
    assert 0.0 < LOW_RELEVANCE_THRESHOLD < PROMOTION_THRESHOLD <= 1.0
    assert PROMOTION_THRESHOLD == pytest.approx(0.15, abs=1e-9)


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
