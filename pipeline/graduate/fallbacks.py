"""Fallback helpers for the graduation CLI.

When Kimi extraction returns a low-confidence value for a *non-judgement*
field (license, description, stars, timestamps), we would rather pull the
ground truth out of the GitHub API payload we already stored in
``raw_search_results.raw_json`` than emit a ``REVIEW_REQUIRED`` sentinel
that the reviewer has to hand-fill.

The rules per field live in :func:`apply_field_fallback`. They are driven
by a data-only ``raw_json`` payload so the logic is fully unit-testable
without a database: tests pass a dict in directly; the CLI uses
:func:`make_raw_payload_fetcher` to build a cached, DB-backed fetcher.

Explicitly out of scope for fallback:

  * ``control_paradigm``, ``temporal_phase``, ``autonomy_level`` — these
    are editorial judgement calls, not data we can recover from GitHub.
  * ``addresses_failure_modes``, ``locus_of_control`` — same.

For those fields we leave the decision alone and let the CLI emit
``REVIEW_REQUIRED`` as it does today.
"""

from __future__ import annotations

import datetime as dt
from typing import Any, Callable, Optional

from psycopg.rows import dict_row

from pipeline import db
from pipeline.dedup import canonical_github_url


# Fields where a GitHub-API fallback is *allowed*. The CLI consults this
# set before attempting any fallback; strict enum / editorial fields are
# deliberately absent.
FALLBACK_ELIGIBLE_FIELDS: frozenset[str] = frozenset({
    "license_spdx",
    "description",
    "tagline",
    "first_released",
    "last_updated",
    "stars",
})

# Confidence below this triggers the fallback ladder.
FALLBACK_THRESHOLD_DEFAULT = 0.85
# Above this Kimi value is preferred over GitHub even if still below the
# auto-accept threshold — Kimi's description is usually richer than a
# one-liner GitHub repo description once it has >= 0.5 confidence.
KIMI_KEEP_THRESHOLD = 0.5
# 140 chars is the schema max_length for ``tagline`` on Tool.
TAGLINE_MAX_CHARS = 140


# ---------------------------------------------------------------------------
# raw_json unwrapping
# ---------------------------------------------------------------------------


def _unwrap_github_payload(raw_json: Any) -> Optional[dict]:
    """Return the actual GitHub-API item dict from whatever we stored.

    :func:`pipeline.sources.github.search_code` wraps the item as
    ``{"query": <q>, "result": <item>}``, so the fields we care about
    (``license.spdx_id`` etc.) live under ``raw_json["result"]``. Older
    rows or direct inserts may have stored the item at the top level.
    """
    if not isinstance(raw_json, dict):
        return None
    result = raw_json.get("result")
    if isinstance(result, dict):
        return result
    # Heuristic: top-level looks like a GitHub repo item if it carries
    # any of the identifying keys we rely on.
    if any(k in raw_json for k in ("license", "stargazers_count", "full_name", "pushed_at")):
        return raw_json
    return None


# ---------------------------------------------------------------------------
# DB-backed fetcher with per-run cache
# ---------------------------------------------------------------------------


def fetch_raw_github_payload(source_url: str) -> Optional[dict]:
    """Return the most-recent GitHub ``raw_json->result`` for ``source_url``.

    Canonicalises ``source_url`` so ``/tree/main`` / ``.git`` suffixes
    / case differences all resolve to the same repo. Returns ``None``
    when no matching ``raw_search_results`` row exists (or the row is
    not a GitHub payload we recognise).
    """
    if not source_url:
        return None
    canon = canonical_github_url(source_url)
    # If we can't canonicalise (non-github URL, malformed), try a direct
    # match on the source_url as-is so non-github sources aren't totally
    # excluded — but the payload shape check below will still veto
    # anything that isn't recognisable.
    target = canon or source_url

    # We match both the canonical and the as-stored url on the raw row,
    # using ILIKE to paper over trailing slashes / case. Ordering by
    # fetched_at DESC gives us the freshest snapshot.
    sql = """
        SELECT raw_json
        FROM raw_search_results
        WHERE source = 'github'
          AND (url = %s OR url ILIKE %s)
        ORDER BY fetched_at DESC
        LIMIT 1
    """
    like = f"{target.rstrip('/')}%"
    try:
        with db.get_conn() as conn, conn.cursor(row_factory=dict_row) as cur:
            cur.execute(sql, (target, like))
            row = cur.fetchone()
    except Exception:  # noqa: BLE001 — DB may be unavailable in tests
        return None
    if row is None:
        return None
    return _unwrap_github_payload(row.get("raw_json"))


def make_raw_payload_fetcher(
    base: Callable[[str], Optional[dict]] = fetch_raw_github_payload,
) -> Callable[[str], Optional[dict]]:
    """Wrap ``base`` with a per-instance cache keyed on ``source_url``.

    The graduation CLI creates one fetcher per run so re-hitting the DB
    for the same candidate is a no-op.
    """
    cache: dict[str, Optional[dict]] = {}

    def fetch(source_url: str) -> Optional[dict]:
        if source_url in cache:
            return cache[source_url]
        cache[source_url] = base(source_url)
        return cache[source_url]

    return fetch


# ---------------------------------------------------------------------------
# Per-field fallback logic
# ---------------------------------------------------------------------------


def _iso_date_from_github(ts: Any) -> Optional[str]:
    """GitHub returns ISO-8601 timestamps like ``2024-04-23T11:50:23Z``.

    We only want the date portion for the YAML ``first_released`` /
    ``last_updated`` / ``stars_updated_at`` fields.
    """
    if not isinstance(ts, str) or not ts:
        return None
    # Cheap path: ISO-8601 always leads with YYYY-MM-DD.
    head = ts[:10]
    try:
        dt.date.fromisoformat(head)
    except ValueError:
        return None
    return head


def _github_spdx(raw: Optional[dict]) -> Optional[str]:
    """Return a usable SPDX id from the GitHub payload, else None.

    GitHub uses ``"NOASSERTION"`` for repos it can't classify; treat that
    as equivalent to missing so the reviewer still sees REVIEW_REQUIRED
    rather than a meaningless string.
    """
    if not isinstance(raw, dict):
        return None
    lic = raw.get("license")
    if not isinstance(lic, dict):
        return None
    spdx = lic.get("spdx_id")
    if not isinstance(spdx, str):
        return None
    spdx = spdx.strip()
    if not spdx or spdx.upper() == "NOASSERTION":
        return None
    return spdx


def _github_description(raw: Optional[dict]) -> Optional[str]:
    if not isinstance(raw, dict):
        return None
    desc = raw.get("description")
    if not isinstance(desc, str):
        return None
    desc = desc.strip()
    return desc or None


class FallbackResult:
    """Outcome of a single field fallback attempt.

    ``accepted`` mirrors :class:`graduate.Decision.accepted`: True means
    the rendered YAML can use ``value`` directly; False means the CLI
    should fall through to its existing REVIEW_REQUIRED path. When
    ``accepted`` is True, ``comment`` carries a short trailing-line
    comment describing the provenance (``fallback=github-api license``,
    ``kimi-conf=0.72`` etc.).
    """

    __slots__ = ("value", "comment", "accepted")

    def __init__(self, value: Any, *, comment: str = "", accepted: bool = True) -> None:
        self.value = value
        self.comment = comment
        self.accepted = accepted

    def __repr__(self) -> str:  # pragma: no cover — debugging aid
        return (
            f"FallbackResult(value={self.value!r}, comment={self.comment!r},"
            f" accepted={self.accepted})"
        )


def apply_field_fallback(
    field: str,
    *,
    kimi_value: Any,
    kimi_confidence: float,
    raw: Optional[dict],
    today: Optional[dt.date] = None,
    threshold: float = FALLBACK_THRESHOLD_DEFAULT,
) -> Optional[FallbackResult]:
    """Compute the fallback value for one field.

    Returns ``None`` when:
      * ``field`` is not eligible for fallback (editorial / enum), OR
      * Kimi's confidence is already >= ``threshold`` (caller already
        accepted the value), OR
      * no fallback source could satisfy the field — caller should emit
        its existing REVIEW_REQUIRED sentinel.

    Returns a :class:`FallbackResult` when a usable value was found; the
    caller should write ``value`` to the YAML and attach ``comment`` as a
    trailing comment on that line.
    """
    if field not in FALLBACK_ELIGIBLE_FIELDS:
        return None
    today = today or dt.date.today()

    if field == "license_spdx":
        if kimi_confidence >= threshold and isinstance(kimi_value, str) and kimi_value.strip():
            return None  # caller keeps the Kimi value
        spdx = _github_spdx(raw)
        if spdx:
            return FallbackResult(spdx, comment="fallback=github-api license.spdx_id")
        return None

    if field == "description":
        # Tier 1: Kimi already passed the auto-accept bar — not our
        # problem, caller will use it.
        if kimi_confidence >= threshold and isinstance(kimi_value, str) and kimi_value.strip():
            return None
        # Tier 2: Kimi still has useful signal — keep it but flag conf.
        if (
            isinstance(kimi_value, str)
            and kimi_value.strip()
            and kimi_confidence >= KIMI_KEEP_THRESHOLD
        ):
            return FallbackResult(
                kimi_value.strip(),
                comment=f"kimi-conf={kimi_confidence:.2f}",
            )
        # Tier 3: GitHub repo description.
        gh_desc = _github_description(raw)
        if gh_desc:
            return FallbackResult(gh_desc, comment="fallback=github-api description")
        return None

    if field == "tagline":
        # Same three tiers as description.
        if kimi_confidence >= threshold and isinstance(kimi_value, str) and kimi_value.strip():
            return None
        if (
            isinstance(kimi_value, str)
            and kimi_value.strip()
            and kimi_confidence >= KIMI_KEEP_THRESHOLD
        ):
            # Still respect the schema's 140-char limit.
            v = kimi_value.strip()[:TAGLINE_MAX_CHARS]
            return FallbackResult(v, comment=f"kimi-conf={kimi_confidence:.2f}")
        gh_desc = _github_description(raw)
        if gh_desc:
            truncated = gh_desc[:TAGLINE_MAX_CHARS]
            note = (
                "fallback=github-api description truncated"
                if len(gh_desc) > TAGLINE_MAX_CHARS
                else "fallback=github-api description"
            )
            return FallbackResult(truncated, comment=note)
        return None

    if field == "first_released":
        # Kimi doesn't own this field today; we always try GitHub.
        if isinstance(raw, dict):
            iso = _iso_date_from_github(raw.get("created_at"))
            if iso:
                return FallbackResult(iso, comment="fallback=github-api created_at")
        return None

    if field == "last_updated":
        if isinstance(raw, dict):
            iso = _iso_date_from_github(raw.get("pushed_at"))
            if iso:
                return FallbackResult(iso, comment="fallback=github-api pushed_at")
        return None

    if field == "stars":
        if isinstance(raw, dict):
            count = raw.get("stargazers_count")
            if isinstance(count, int) and count >= 0:
                return FallbackResult(
                    {"stars": count, "stars_updated_at": today.isoformat()},
                    comment="fallback=github-api stargazers_count",
                )
        return None

    return None  # pragma: no cover — guarded by FALLBACK_ELIGIBLE_FIELDS


__all__ = [
    "FALLBACK_ELIGIBLE_FIELDS",
    "FALLBACK_THRESHOLD_DEFAULT",
    "FallbackResult",
    "KIMI_KEEP_THRESHOLD",
    "TAGLINE_MAX_CHARS",
    "apply_field_fallback",
    "fetch_raw_github_payload",
    "make_raw_payload_fetcher",
]
