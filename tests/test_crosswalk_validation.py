"""Unit tests for the crosswalk-category cross-invariants added to
``validator/cli.py``.

We drive ``cross_invariants`` by monkeypatching ``iter_nodes`` so we can
inject small, controlled fixtures for taxonomies / crosswalks / failure
modes. That keeps tests fast (no filesystem) and lets us exercise the
exact error strings a bad PR would surface.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from validator import cli as validator_cli


# ---------------------------------------------------------------------------
# Fixture scaffolding
# ---------------------------------------------------------------------------


_FAKE_TAXONOMY_OWASP = {
    "id": "owasp-agentic-top-10-2026",
    "categories": [
        {"external_id": "ASI01", "label": "Goal hijack"},
        {"external_id": "ASI02", "label": "Tool misuse"},
        {"external_id": "ASI04", "label": "Supply chain"},
    ],
}


def _install_fake_corpus(
    monkeypatch: pytest.MonkeyPatch,
    *,
    tools: list[dict[str, Any]] | None = None,
    modes: list[dict[str, Any]] | None = None,
    papers: list[dict[str, Any]] | None = None,
    taxonomies: list[dict[str, Any]] | None = None,
    crosswalks: list[dict[str, Any]] | None = None,
) -> None:
    """Replace ``iter_nodes`` so ``cross_invariants`` sees our fixtures."""
    fixtures = {
        "tools": tools or [],
        "failure_modes": modes or [],
        "papers": papers or [],
        "taxonomies": taxonomies or [],
        "crosswalks": crosswalks or [],
    }

    def fake_iter(kind: str) -> list[tuple[Path, dict[str, Any]]]:
        return [(Path(f"{kind}/{n['id']}.yml"), n) for n in fixtures.get(kind, [])]

    monkeypatch.setattr(validator_cli, "iter_nodes", fake_iter)
    # Point MANIFEST_PATH at a nonexistent file so the manifest-lock check
    # is effectively skipped. Each test opts in explicitly when it wants
    # manifest coverage.
    monkeypatch.setattr(
        validator_cli,
        "MANIFEST_PATH",
        Path("/tmp/does-not-exist-manifest.json"),
    )


def _run_invariants() -> tuple[list[str], list[str]]:
    warn: list[str] = []
    err: list[str] = []
    validator_cli.cross_invariants(warn, err)
    return warn, err


# ---------------------------------------------------------------------------
# Standalone Crosswalk nodes
# ---------------------------------------------------------------------------


def test_valid_crosswalk_passes(monkeypatch: pytest.MonkeyPatch) -> None:
    """All mapping external_ids present in the taxonomy → no errors."""
    crosswalk = {
        "id": "owasp-to-saica",
        "saica_axis": "failure_mode",
        "taxonomy": "owasp-agentic-top-10-2026",
        "mappings": [
            {
                "saica_value": "scope_creep",
                "external_id": "ASI01",
                "confidence": "partial",
            },
            {
                "saica_value": "supply_chain_attack",
                "external_id": "ASI04",
                "confidence": "exact",
            },
        ],
    }
    _install_fake_corpus(
        monkeypatch,
        taxonomies=[_FAKE_TAXONOMY_OWASP],
        crosswalks=[crosswalk],
    )

    _, err = _run_invariants()
    crosswalk_errors = [e for e in err if "[crosswalks]" in e]
    assert crosswalk_errors == []


def test_crosswalk_to_missing_taxonomy_errors(monkeypatch: pytest.MonkeyPatch) -> None:
    """A crosswalk pointing at a non-existent taxonomy must flag an error."""
    crosswalk = {
        "id": "phantom-to-saica",
        "saica_axis": "failure_mode",
        "taxonomy": "does-not-exist",
        "mappings": [
            {
                "saica_value": "scope_creep",
                "external_id": "X01",
                "confidence": "partial",
            },
        ],
    }
    _install_fake_corpus(
        monkeypatch,
        taxonomies=[_FAKE_TAXONOMY_OWASP],
        crosswalks=[crosswalk],
    )

    _, err = _run_invariants()
    assert any(
        "[crosswalks]" in e and "phantom-to-saica" in e and "does-not-exist" in e
        for e in err
    ), f"expected missing-taxonomy error; got: {err}"
    # And once we've reported the missing taxonomy, we do NOT cascade into
    # per-mapping errors for that crosswalk.
    assert not any("X01" in e for e in err)


def test_crosswalk_with_unknown_external_id_errors(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A mapping to an external_id that isn't in the taxonomy's categories
    must produce a targeted error naming both the saica_value and the bad
    external_id.
    """
    crosswalk = {
        "id": "owasp-to-saica",
        "saica_axis": "failure_mode",
        "taxonomy": "owasp-agentic-top-10-2026",
        "mappings": [
            {
                "saica_value": "scope_creep",
                "external_id": "ASI01",
                "confidence": "partial",
            },
            # ASI99 does not exist in the taxonomy — bug.
            {
                "saica_value": "fabrication",
                "external_id": "ASI99",
                "confidence": "related",
            },
        ],
    }
    _install_fake_corpus(
        monkeypatch,
        taxonomies=[_FAKE_TAXONOMY_OWASP],
        crosswalks=[crosswalk],
    )

    _, err = _run_invariants()
    matching = [
        e for e in err if "[crosswalks]" in e and "owasp-to-saica" in e and "ASI99" in e
    ]
    assert matching, f"expected unknown-external_id error; got: {err}"
    # And the other (valid) mapping is NOT flagged.
    assert not any("ASI01" in e for e in err)


# ---------------------------------------------------------------------------
# Inline FailureMode crosswalks
# ---------------------------------------------------------------------------


def test_inline_failure_mode_crosswalk_validated(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """FailureMode.crosswalks[*].external_id is checked with the same rule."""
    mode = {
        "id": "scope_creep",
        "name": "Scope creep",
        "crosswalks": [
            # Good mapping.
            {
                "taxonomy": "owasp-agentic-top-10-2026",
                "external_id": "ASI02",
                "confidence": "partial",
            },
            # Bad mapping — ASI77 is not in the OWASP taxonomy.
            {
                "taxonomy": "owasp-agentic-top-10-2026",
                "external_id": "ASI77",
                "confidence": "related",
            },
        ],
    }
    _install_fake_corpus(
        monkeypatch,
        taxonomies=[_FAKE_TAXONOMY_OWASP],
        modes=[mode],
    )

    _, err = _run_invariants()
    bad = [
        e for e in err if "[failure_modes]" in e and "scope_creep" in e and "ASI77" in e
    ]
    assert bad, f"expected inline-crosswalk error on ASI77; got: {err}"
    # The ASI02 row (which is valid) should NOT show up as an error.
    assert not any(
        "[failure_modes]" in e and "ASI02" in e for e in err
    ), f"valid ASI02 mapping falsely flagged: {err}"


def test_inline_failure_mode_crosswalk_missing_taxonomy(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Inline crosswalk on a FailureMode with a missing taxonomy errors and
    does NOT then also try to match the external_id against an empty
    category set (avoid cascading errors)."""
    mode = {
        "id": "fabrication",
        "crosswalks": [
            {
                "taxonomy": "non-existent-taxonomy",
                "external_id": "X-01",
                "confidence": "related",
            },
        ],
    }
    _install_fake_corpus(
        monkeypatch,
        taxonomies=[_FAKE_TAXONOMY_OWASP],
        modes=[mode],
    )

    _, err = _run_invariants()
    tax_errors = [e for e in err if "non-existent-taxonomy" in e]
    assert tax_errors, f"expected missing-taxonomy error; got: {err}"
    # No cascaded "X-01 is not a category" error.
    assert not any("X-01" in e for e in err)


def test_corpus_has_no_crosswalk_violations(monkeypatch: pytest.MonkeyPatch) -> None:
    """End-to-end: the committed corpus must pass the new crosswalk check.

    This is the anti-regression guardrail — once CI is green, it stays
    green. Any future taxonomy edit that drops a category referenced by a
    crosswalk will flip this test red immediately.
    """
    # We deliberately do NOT monkeypatch here — we want the real data.
    warn: list[str] = []
    err: list[str] = []
    validator_cli.cross_invariants(warn, err)

    crosswalk_errors = [
        e
        for e in err
        if "[crosswalks]" in e or ("[failure_modes]" in e and "crosswalk" in e)
    ]
    assert (
        crosswalk_errors == []
    ), "current corpus has crosswalk-category violations:\n  " + "\n  ".join(
        crosswalk_errors
    )
