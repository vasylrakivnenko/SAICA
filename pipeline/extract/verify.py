"""Stage 7a — substring verification of LLM evidence quotes.

For each ``ConfidenceField`` on an extraction (see
:mod:`pipeline.extract.schemas`), the LLM is required to attach
``evidence: list[str]`` — direct quotes from the source supporting the
extracted ``value``. This module verifies, deterministically, that
each of those quotes actually appears in the source text.

Why deterministic verification matters
--------------------------------------
LLMs that "self-rate confidence" still hallucinate plausibly — they
*invent* supporting quotes that read like they came from the source
but don't. ``ConfidenceField.evidence`` lets us catch this without
another model call: if the quote isn't a substring of the source
(modulo whitespace + case), the LLM made it up.

Verification is intentionally lenient on whitespace + case but strict
on token-level content. We do NOT do fuzzy matching, paraphrase
detection, or semantic equivalence — those would re-introduce the
hallucination risk we're trying to eliminate.

Output shape
------------
``verify_extraction(extraction, source_text) -> ExtractionVerification``

The returned object exposes per-field verification results plus a
flat helper ``unverified_fields()`` listing field names whose evidence
list contains *any* quote that didn't substring-match the source.
Callers (graduate scripts, the triage UI, the YAML stub renderer)
decide how to surface this — typically by tagging the corresponding
YAML key with ``# REVIEW REQUIRED``.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Iterable

from pipeline.extract.schemas import ConfidenceField

# Whitespace normalisation collapses every run of whitespace (incl. NBSP +
# common Unicode spaces) to a single ASCII space so quotes copied from PDFs,
# HTML, or markdown all match the way the model emitted them.
_WHITESPACE_RE = re.compile(r"\s+")
_NBSP_AND_FRIENDS = str.maketrans({c: " " for c in "    ​"})


def _normalise(text: str) -> str:
    """Lower-case + collapse whitespace + strip wrapping quote chars."""
    if not text:
        return ""
    cleaned = text.translate(_NBSP_AND_FRIENDS)
    cleaned = _WHITESPACE_RE.sub(" ", cleaned).strip().lower()
    # Strip wrapping quotes the LLM sometimes adds when copying ("foo bar").
    if cleaned and cleaned[0] in {'"', "'", "“", "‘"}:
        cleaned = cleaned[1:]
    if cleaned and cleaned[-1] in {'"', "'", "”", "’"}:
        cleaned = cleaned[:-1]
    return cleaned.strip()


@dataclass
class FieldVerification:
    """Result of verifying one ``ConfidenceField``'s evidence list."""

    field_name: str
    quotes_total: int
    quotes_verified: int
    unverified_quotes: list[str] = field(default_factory=list)

    @property
    def all_verified(self) -> bool:
        return self.quotes_total > 0 and self.quotes_verified == self.quotes_total

    @property
    def has_evidence(self) -> bool:
        return self.quotes_total > 0


@dataclass
class ExtractionVerification:
    """Per-field verification across a whole ``*Extraction``."""

    fields: dict[str, FieldVerification] = field(default_factory=dict)

    def unverified_fields(self) -> list[str]:
        """Field names with at least one quote that didn't substring-match.

        A field with zero evidence quotes is NOT counted as unverified —
        that's a different shape of problem (no evidence at all) and is
        better surfaced by the calibration / confidence threshold layer.
        """
        return sorted(
            name
            for name, fv in self.fields.items()
            if fv.has_evidence and not fv.all_verified
        )

    @property
    def all_verified(self) -> bool:
        """True iff every field with evidence has 100% verified quotes."""
        return all(
            fv.all_verified for fv in self.fields.values() if fv.has_evidence
        )


def verify_quote(quote: str, source_normalised: str) -> bool:
    """Return True iff ``quote`` (after normalisation) is a substring of
    the already-normalised source.

    Splitting normalisation between caller and callee lets a verifier
    over many fields normalise the source exactly once.
    """
    return _normalise(quote) in source_normalised if quote else False


def verify_field(
    field_name: str,
    confidence_field: ConfidenceField,
    *,
    source_normalised: str,
) -> FieldVerification:
    """Verify one ``ConfidenceField``'s evidence list."""
    quotes = confidence_field.evidence or []
    unverified = [q for q in quotes if not verify_quote(q, source_normalised)]
    return FieldVerification(
        field_name=field_name,
        quotes_total=len(quotes),
        quotes_verified=len(quotes) - len(unverified),
        unverified_quotes=unverified,
    )


def verify_extraction(extraction: Any, source_text: str) -> ExtractionVerification:
    """Verify every ``ConfidenceField`` on a ``ToolExtraction`` /
    ``PaperExtraction``.

    Iterates the model's fields by name (Pydantic v2 ``model_fields``)
    and checks any field whose runtime value is a ``ConfidenceField``.
    Non-evidence fields (e.g. ``overall_confidence: float``) are skipped.
    """
    src = _normalise(source_text)
    results = ExtractionVerification()
    for name, _info in type(extraction).model_fields.items():
        value = getattr(extraction, name, None)
        if isinstance(value, ConfidenceField):
            results.fields[name] = verify_field(
                name, value, source_normalised=src
            )
    return results


def review_required_fields(
    extraction: Any,
    source_text: str,
    *,
    require_evidence: Iterable[str] = (),
) -> set[str]:
    """Convenience: returns the set of field names that need
    ``# REVIEW REQUIRED`` in the YAML stub.

    Includes:
      * fields with at least one unverified quote (Stage 7a violation);
      * fields named in ``require_evidence`` that have no evidence
        quotes at all (a stricter rule for taxonomy-bound fields).
    """
    verification = verify_extraction(extraction, source_text)
    needs_review = set(verification.unverified_fields())
    require_set = set(require_evidence)
    if require_set:
        for name in require_set:
            fv = verification.fields.get(name)
            if fv is None or not fv.has_evidence:
                needs_review.add(name)
    return needs_review


__all__ = [
    "ExtractionVerification",
    "FieldVerification",
    "review_required_fields",
    "verify_extraction",
    "verify_field",
    "verify_quote",
]
