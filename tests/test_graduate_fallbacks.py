"""Tests for the graduation CLI's GitHub-API fallback ladder.

These tests exercise :mod:`pipeline.graduate.fallbacks` directly with
dict fixtures (no DB) and also drive the full tool-YAML build path to
confirm the CLI's rendering picks up fallback values in place of
``REVIEW_REQUIRED`` sentinels.

The editorial enum fields (``control_paradigm`` etc.) are explicitly
asserted to stay unchanged — the fallback module MUST NOT guess them
from the GitHub payload even when it could.
"""

from __future__ import annotations

import datetime as dt
from typing import Any

import pytest

from pipeline.cli.graduate import Decision, _build_tool_yaml
from pipeline.graduate.fallbacks import (
    FALLBACK_ELIGIBLE_FIELDS,
    apply_field_fallback,
    make_raw_payload_fetcher,
)


# ---------------------------------------------------------------------------
# Fixtures — a canonical GitHub-API "item" as the repository search endpoint
# returns it, trimmed to the fields the fallback ladder actually reads.
# ---------------------------------------------------------------------------


def _github_item(**overrides: Any) -> dict:
    item = {
        "full_name": "acme/widget",
        "description": "A widget that does widget things for LLM agents.",
        "license": {"key": "mit", "spdx_id": "MIT", "name": "MIT License"},
        "created_at": "2022-03-15T10:20:30Z",
        "pushed_at": "2026-04-22T09:00:00Z",
        "stargazers_count": 4242,
    }
    item.update(overrides)
    return item


def _tool_row(source_url: str = "https://github.com/acme/widget") -> dict:
    return {"id": 1, "source_url": source_url, "proposed_id": "widget"}


def _all_decisions(
    *,
    license_conf: float = 0.2,
    description_value: str = "",
    description_conf: float = 0.0,
    tagline_value: str = "",
    tagline_conf: float = 0.0,
    control_paradigm_conf: float = 0.3,
    name_conf: float = 0.95,
) -> dict[str, Decision]:
    """Build the full decisions dict the tool YAML builder expects.

    Callers only need to override the fields that matter to their test;
    everything else is low-confidence / rejected so the fallback ladder
    is the one making the call.
    """
    return {
        "proposed_id": Decision("widget", 0.95, accepted=True),
        "name": Decision("Widget", name_conf, accepted=name_conf >= 0.85),
        "tagline": Decision(
            tagline_value, tagline_conf, accepted=tagline_conf >= 0.85
        ),
        "description": Decision(
            description_value,
            description_conf,
            accepted=description_conf >= 0.85,
        ),
        "repository_url": Decision(
            "https://github.com/acme/widget", 0.95, accepted=True
        ),
        "license_spdx": Decision(None, license_conf, accepted=False),
        "control_paradigm": Decision(
            None, control_paradigm_conf, accepted=False
        ),
        "temporal_phase": Decision(None, 0.3, accepted=False),
        "autonomy_level": Decision(None, 0.3, accepted=False),
        "addresses_failure_modes": Decision([], 0.3, accepted=False),
        "locus_of_control": Decision([], 0.3, accepted=False),
        "inclusion_rationale": Decision(None, 0.3, accepted=False),
    }


def _build(decisions: dict[str, Decision], raw: Any) -> dict:
    """Render the tool YAML and return it as a plain dict for assertion."""
    fetcher = lambda url: raw  # noqa: E731
    _, doc = _build_tool_yaml(
        _tool_row(),
        {"overall_confidence": 0.5},
        decisions,
        today=dt.date(2026, 4, 23),
        auto_threshold=0.85,
        fetch_raw=fetcher,
    )
    # CommentedMap is a dict subclass — values round-trip as-is.
    return dict(doc)


# ---------------------------------------------------------------------------
# License ladder
# ---------------------------------------------------------------------------


def test_license_falls_back_to_github_when_kimi_low_confidence() -> None:
    result = apply_field_fallback(
        "license_spdx",
        kimi_value=None,
        kimi_confidence=0.2,
        raw=_github_item(),
    )
    assert result is not None
    assert result.value == "MIT"
    assert "fallback=github-api" in result.comment

    # End-to-end through the YAML builder, too.
    doc = _build(_all_decisions(license_conf=0.2), _github_item())
    assert doc["license"] == "MIT"


def test_license_uses_kimi_when_confidence_high() -> None:
    # When Kimi already clears the auto-accept threshold, the fallback
    # module must stay out of the way.
    result = apply_field_fallback(
        "license_spdx",
        kimi_value="Apache-2.0",
        kimi_confidence=0.95,
        raw=_github_item(license={"spdx_id": "MIT"}),
    )
    assert result is None  # caller keeps Kimi's Apache-2.0

    decisions = _all_decisions()
    decisions["license_spdx"] = Decision("Apache-2.0", 0.95, accepted=True)
    doc = _build(decisions, _github_item(license={"spdx_id": "MIT"}))
    assert doc["license"] == "Apache-2.0"


def test_license_review_required_when_both_missing() -> None:
    # Kimi low-conf AND GitHub has no license info -> caller must fall
    # through to its REVIEW_REQUIRED path.
    result = apply_field_fallback(
        "license_spdx",
        kimi_value=None,
        kimi_confidence=0.2,
        raw=_github_item(license=None),
    )
    assert result is None

    doc = _build(_all_decisions(license_conf=0.2), _github_item(license=None))
    assert doc["license"] == "REVIEW_REQUIRED"


def test_noassertion_license_falls_to_review_required() -> None:
    # GitHub uses "NOASSERTION" for repos it can't classify; we treat
    # that the same as a missing license so the reviewer still has to
    # look at it.
    result = apply_field_fallback(
        "license_spdx",
        kimi_value=None,
        kimi_confidence=0.2,
        raw=_github_item(license={"spdx_id": "NOASSERTION"}),
    )
    assert result is None

    doc = _build(
        _all_decisions(license_conf=0.2),
        _github_item(license={"spdx_id": "NOASSERTION"}),
    )
    assert doc["license"] == "REVIEW_REQUIRED"


# ---------------------------------------------------------------------------
# Description / tagline ladder
# ---------------------------------------------------------------------------


def test_description_tier_falls_through_to_github_desc() -> None:
    # Kimi is empty/low-conf AND below the 0.5 keep-threshold: we reach
    # for the GitHub repo description.
    result = apply_field_fallback(
        "description",
        kimi_value="",
        kimi_confidence=0.1,
        raw=_github_item(description="Evaluates LLM agent outputs."),
    )
    assert result is not None
    assert result.value == "Evaluates LLM agent outputs."
    assert "fallback=github-api" in result.comment

    # Tier 2: Kimi in the 0.5-0.85 band -> keep Kimi's richer value.
    kept = apply_field_fallback(
        "description",
        kimi_value="A Kimi-written longer paragraph about the tool.",
        kimi_confidence=0.7,
        raw=_github_item(description="short github desc"),
    )
    assert kept is not None
    assert kept.value == "A Kimi-written longer paragraph about the tool."
    assert "kimi-conf=0.70" in kept.comment


def test_tagline_truncates_github_desc_to_140() -> None:
    long_desc = "x" * 300
    result = apply_field_fallback(
        "tagline",
        kimi_value="",
        kimi_confidence=0.1,
        raw=_github_item(description=long_desc),
    )
    assert result is not None
    assert len(result.value) == 140
    assert result.value == "x" * 140
    assert "truncated" in result.comment


# ---------------------------------------------------------------------------
# first_released / stars
# ---------------------------------------------------------------------------


def test_first_released_uses_created_at() -> None:
    result = apply_field_fallback(
        "first_released",
        kimi_value=None,
        kimi_confidence=0.0,
        raw=_github_item(created_at="2020-11-02T21:56:45Z"),
    )
    assert result is not None
    assert result.value == "2020-11-02"
    assert "created_at" in result.comment

    # End-to-end: the YAML scaffolding no longer falls back to "today".
    doc = _build(_all_decisions(), _github_item(created_at="2020-11-02T21:56:45Z"))
    assert doc["first_released"] == "2020-11-02"


def test_stars_populated_from_stargazers_count() -> None:
    today = dt.date(2026, 4, 23)
    result = apply_field_fallback(
        "stars",
        kimi_value=None,
        kimi_confidence=0.0,
        raw=_github_item(stargazers_count=12345),
        today=today,
    )
    assert result is not None
    assert result.value == {"stars": 12345, "stars_updated_at": "2026-04-23"}

    doc = _build(_all_decisions(), _github_item(stargazers_count=12345))
    assert doc["stars"] == 12345
    assert doc["stars_updated_at"] == "2026-04-23"


# ---------------------------------------------------------------------------
# Strict enum fields — never guess from GitHub
# ---------------------------------------------------------------------------


def test_strict_enum_fields_never_guess() -> None:
    # Editorial fields are NOT eligible for fallback. Even with a fat
    # GitHub payload, the module must return None and let the CLI emit
    # REVIEW_REQUIRED.
    for field in (
        "control_paradigm",
        "temporal_phase",
        "autonomy_level",
        "addresses_failure_modes",
        "locus_of_control",
    ):
        assert field not in FALLBACK_ELIGIBLE_FIELDS, (
            f"{field} must never be populated from GitHub data"
        )
        result = apply_field_fallback(
            field,
            kimi_value=None,
            kimi_confidence=0.1,
            raw=_github_item(),
        )
        assert result is None

    # End-to-end: the rendered YAML still carries REVIEW_REQUIRED on
    # control_paradigm even though the raw payload has plenty of signal.
    doc = _build(_all_decisions(control_paradigm_conf=0.1), _github_item())
    assert doc["control_paradigm"] == "REVIEW_REQUIRED"
    assert doc["temporal_phase"] == "REVIEW_REQUIRED"
    assert doc["autonomy_level"] == "REVIEW_REQUIRED"


# ---------------------------------------------------------------------------
# Fetcher cache
# ---------------------------------------------------------------------------


def test_fetcher_caches_per_source_url() -> None:
    calls: list[str] = []

    def fake(url: str) -> dict:
        calls.append(url)
        return _github_item()

    fetch = make_raw_payload_fetcher(base=fake)
    fetch("https://github.com/acme/widget")
    fetch("https://github.com/acme/widget")
    fetch("https://github.com/acme/other")

    assert calls == [
        "https://github.com/acme/widget",
        "https://github.com/acme/other",
    ]


# ---------------------------------------------------------------------------
# Edge cases
# ---------------------------------------------------------------------------


def test_missing_raw_payload_yields_none() -> None:
    # No raw data at all -> every data-recovery field returns None.
    for field in ("license_spdx", "first_released", "last_updated", "stars"):
        assert (
            apply_field_fallback(
                field,
                kimi_value=None,
                kimi_confidence=0.0,
                raw=None,
            )
            is None
        )


def test_malformed_created_at_does_not_crash() -> None:
    result = apply_field_fallback(
        "first_released",
        kimi_value=None,
        kimi_confidence=0.0,
        raw=_github_item(created_at="not-a-date"),
    )
    assert result is None
