"""Unit tests for ``pipeline.dedup``.

These tests are fully offline — the one test that exercises the
``candidate_tools`` path monkeypatches ``DupChecker._load_candidate_index``
so we don't need a live Postgres.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from pipeline.dedup import (
    DupChecker,
    DupHit,
    canonical_github_url,
    canonical_repo_key,
)


REPO_ROOT = Path(__file__).resolve().parent.parent
YAML_DIR = str(REPO_ROOT / "data" / "tools")


# ---------------------------------------------------------------------------
# canonical_github_url
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "url,expected",
    [
        # 1. baseline
        (
            "https://github.com/pydantic/pydantic-ai",
            "https://github.com/pydantic/pydantic-ai",
        ),
        # 2. trailing slash
        (
            "https://github.com/pydantic/pydantic-ai/",
            "https://github.com/pydantic/pydantic-ai",
        ),
        # 3. .git suffix
        (
            "https://github.com/pydantic/pydantic-ai.git",
            "https://github.com/pydantic/pydantic-ai",
        ),
        # 4. tree/<branch>/<path>
        (
            "https://github.com/pydantic/pydantic-ai/tree/main/docs",
            "https://github.com/pydantic/pydantic-ai",
        ),
        # 5. blob/<branch>/<file>
        (
            "https://github.com/pydantic/pydantic-ai/blob/main/README.md",
            "https://github.com/pydantic/pydantic-ai",
        ),
        # 6. mixed case host + path
        (
            "https://GitHub.com/Pydantic/pydantic-ai/",
            "https://github.com/pydantic/pydantic-ai",
        ),
        # 7. http -> https
        (
            "http://github.com/pydantic/pydantic-ai",
            "https://github.com/pydantic/pydantic-ai",
        ),
        # 8. query string + fragment
        (
            "https://github.com/pydantic/pydantic-ai?foo=bar#readme",
            "https://github.com/pydantic/pydantic-ai",
        ),
        # 9. issues subpath
        (
            "https://github.com/pydantic/pydantic-ai/issues/42",
            "https://github.com/pydantic/pydantic-ai",
        ),
        # 10. pulls subpath
        (
            "https://github.com/pydantic/pydantic-ai/pulls",
            "https://github.com/pydantic/pydantic-ai",
        ),
        # 11. releases subpath
        (
            "https://github.com/pydantic/pydantic-ai/releases/tag/v0.1.0",
            "https://github.com/pydantic/pydantic-ai",
        ),
        # 12. www.github.com folded to github.com
        (
            "https://www.github.com/pydantic/pydantic-ai",
            "https://github.com/pydantic/pydantic-ai",
        ),
        # 13. bare host (no scheme)
        (
            "github.com/pydantic/pydantic-ai",
            "https://github.com/pydantic/pydantic-ai",
        ),
        # 14. non-GitHub host rejected
        ("https://gitlab.com/pydantic/pydantic-ai", None),
        # 15. docs site rejected
        ("https://ai.pydantic.dev", None),
        # 16. reserved GitHub path rejected
        ("https://github.com/marketplace/actions/foo", None),
        # 17. owner-only rejected
        ("https://github.com/pydantic", None),
        # 18. garbage
        ("not a url", None),
        # 19. None-ish
        ("", None),
    ],
)
def test_canonical_github_url(url, expected):
    assert canonical_github_url(url) == expected


def test_canonical_github_url_non_string():
    # Defensive: non-string inputs shouldn't raise.
    assert canonical_github_url(None) is None  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# canonical_repo_key
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "url,expected",
    [
        ("https://github.com/pydantic/pydantic-ai", "pydantic/pydantic-ai"),
        ("https://GitHub.com/Pydantic/Pydantic-AI.git", "pydantic/pydantic-ai"),
        (
            "https://github.com/pydantic/pydantic-ai/tree/main",
            "pydantic/pydantic-ai",
        ),
        ("https://gitlab.com/pydantic/pydantic-ai", None),
        ("not a url", None),
    ],
)
def test_canonical_repo_key(url, expected):
    assert canonical_repo_key(url) == expected


# ---------------------------------------------------------------------------
# DupChecker — YAML population
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def checker_no_db() -> DupChecker:
    """A DupChecker bound to the real data/tools/ dir, without Postgres."""
    return DupChecker(yaml_dir=YAML_DIR, include_candidates=False)


def test_check_url_hits_yaml_exact(checker_no_db: DupChecker):
    hit = checker_no_db.check_url("https://github.com/pydantic/pydantic-ai")
    assert hit is not None
    assert hit.kind == "yaml"
    assert hit.match_id == "pydantic-ai"
    assert hit.match_url == "https://github.com/pydantic/pydantic-ai"
    assert hit.similarity == 1.0
    assert hit.rule == "canonical_url"


def test_check_url_hits_yaml_after_normalization(checker_no_db: DupChecker):
    # trailing slash + uppercase + tree path all still hit the YAML entry.
    hit = checker_no_db.check_url(
        "https://GitHub.com/Pydantic/pydantic-ai/tree/main/docs/"
    )
    assert hit is not None
    assert hit.match_id == "pydantic-ai"
    assert hit.rule == "canonical_url"


def test_check_url_miss_returns_none(checker_no_db: DupChecker):
    assert (
        checker_no_db.check_url("https://github.com/example-org/no-such-repo") is None
    )


def test_check_url_non_github_returns_none(checker_no_db: DupChecker):
    assert checker_no_db.check_url("https://example.com/something") is None


# ---------------------------------------------------------------------------
# DupChecker — candidate population (mocked)
# ---------------------------------------------------------------------------


def test_check_url_hits_candidate(monkeypatch):
    """Seed a fake candidate row via monkeypatching the index loader."""
    from pipeline import dedup as dedup_mod

    def _fake_load(self):  # noqa: ANN001 - method patch
        entry = dedup_mod._IndexEntry(
            kind="candidate",
            match_id="42",
            url="https://github.com/fakeorg/fakerepo",
            repo_key="fakeorg/fakerepo",
            name="FakeRepo",
        )
        self._entries.append(entry)
        self._by_url[entry.url] = entry
        self._by_repo_key[entry.repo_key] = entry

    monkeypatch.setattr(dedup_mod.DupChecker, "_load_candidate_index", _fake_load)
    checker = DupChecker(yaml_dir=YAML_DIR, include_candidates=True)

    hit = checker.check_url("https://github.com/FakeOrg/fakerepo/")
    assert hit is not None
    assert hit.kind == "candidate"
    assert hit.match_id == "42"
    assert hit.similarity == 1.0
    assert hit.rule == "canonical_url"


# ---------------------------------------------------------------------------
# Fuzzy name match
# ---------------------------------------------------------------------------


def test_fuzzy_name_matches_pydantic_ai(checker_no_db: DupChecker):
    # "PydanticAI" should fuzzy-match the YAML name "PydanticAI" trivially,
    # and "pydantic-ai" should match at >= 90 too.
    hit = checker_no_db.check_name("PydanticAI")
    assert hit is not None
    assert hit.similarity >= 0.9
    assert hit.rule == "fuzzy_name"
    assert hit.match_id == "pydantic-ai"

    hit2 = checker_no_db.check_name("pydantic-ai")
    assert hit2 is not None
    assert hit2.similarity >= 0.9
    assert hit2.match_id == "pydantic-ai"


def test_fuzzy_name_returns_none_for_unrelated(checker_no_db: DupChecker):
    assert checker_no_db.check_name("wholly-unrelated-zzz") is None


def test_check_url_falls_back_to_fuzzy_name(checker_no_db: DupChecker):
    # Non-GitHub URL but name matches an indexed YAML.
    hit = checker_no_db.check_url("https://example.com/whatever", name="PydanticAI")
    assert hit is not None
    assert hit.rule == "fuzzy_name"
    assert hit.match_id == "pydantic-ai"


# ---------------------------------------------------------------------------
# Intra-batch dedup
# ---------------------------------------------------------------------------


def test_register_batch_then_check_hits_batch():
    # Use an empty yaml dir so we only see batch state.
    checker = DupChecker(yaml_dir="/nonexistent-dir", include_candidates=False)
    checker.register_batch(
        "https://github.com/example-org/brand-new-repo", name="BrandNew"
    )

    hit = checker.check_url("https://github.com/example-org/brand-new-repo/tree/main")
    assert hit is not None
    assert hit.kind == "batch"
    assert hit.rule == "canonical_url"
    assert hit.similarity == 1.0
    assert hit.match_url == "https://github.com/example-org/brand-new-repo"


def test_register_batch_first_occurrence_is_not_a_hit():
    checker = DupChecker(yaml_dir="/nonexistent-dir", include_candidates=False)
    # Before registration, no hit.
    assert checker.check_url("https://github.com/example-org/xyz-repo") is None
    checker.register_batch("https://github.com/example-org/xyz-repo")
    # After registration, same URL is a batch hit.
    hit = checker.check_url("https://github.com/example-org/xyz-repo")
    assert hit is not None
    assert hit.kind == "batch"


# ---------------------------------------------------------------------------
# DupHit is a proper dataclass (sanity)
# ---------------------------------------------------------------------------


def test_duphit_fields():
    h = DupHit(
        kind="yaml",
        match_id="x",
        match_url=None,
        match_name=None,
        similarity=1.0,
        rule="canonical_url",
    )
    assert h.kind == "yaml"
    assert h.similarity == 1.0
