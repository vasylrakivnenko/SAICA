"""Postgres-backed response cache for Kimi extractions.

Cache key = SHA-256 of ``(prompt_version, kind, candidate_id, source_url)``.
We don't hash the full prompt body because the prompt is a constant module
attribute (``PROMPT_VERSION`` bumps whenever it changes).

Hit: ``candidate_tools.extracted`` / ``candidate_papers.extracted`` already
contains a JSONB blob with ``_cache_key == <hash>``. We return that and skip
the Kimi call.

Miss: caller must call Kimi, then persist via
``store_extraction(kind, candidate_id, cache_key, payload)``.
"""

from __future__ import annotations

import hashlib
from typing import Any, Optional

from psycopg.rows import dict_row
from psycopg.types.json import Json

from pipeline import db


PROMPT_VERSION = "v1"  # bump when the system prompt or schema changes

_TABLES = {"tools": "candidate_tools", "papers": "candidate_papers"}


def compute_cache_key(
    *,
    kind: str,
    candidate_id: int,
    source_url: str,
    prompt_version: str = PROMPT_VERSION,
) -> str:
    """Return the SHA-256 hex digest for the extraction cache key."""
    h = hashlib.sha256()
    h.update(prompt_version.encode("utf-8"))
    h.update(b"\x00")
    h.update(kind.encode("utf-8"))
    h.update(b"\x00")
    h.update(str(candidate_id).encode("utf-8"))
    h.update(b"\x00")
    h.update((source_url or "").encode("utf-8"))
    return h.hexdigest()


def _table_for(kind: str) -> str:
    try:
        return _TABLES[kind]
    except KeyError as exc:
        raise ValueError(
            f"Unknown cache kind {kind!r}; expected one of {sorted(_TABLES)}"
        ) from exc


def lookup_extraction(kind: str, candidate_id: int, cache_key: str) -> Optional[dict]:
    """Return the cached extraction blob if ``cache_key`` matches; else None."""
    table = _table_for(kind)
    sql = f"SELECT extracted FROM {table} WHERE id = %s"
    with db.get_conn() as conn, conn.cursor(row_factory=dict_row) as cur:
        cur.execute(sql, (candidate_id,))
        row = cur.fetchone()
    if not row:
        return None
    blob = row["extracted"] or {}
    if not isinstance(blob, dict):
        return None
    if blob.get("_cache_key") != cache_key:
        return None
    if not blob.get("payload"):
        return None
    return blob["payload"]


def store_extraction(
    kind: str,
    candidate_id: int,
    cache_key: str,
    payload: dict,
    *,
    model: str = "",
) -> None:
    """Persist extraction payload under the cache key into ``extracted``."""
    table = _table_for(kind)
    envelope: dict[str, Any] = {
        "_cache_key": cache_key,
        "_prompt_version": PROMPT_VERSION,
        "_model": model,
        "payload": payload,
    }
    sql = f"UPDATE {table} SET extracted = %s WHERE id = %s"
    with db.get_conn() as conn, conn.cursor() as cur:
        cur.execute(sql, (Json(envelope), candidate_id))
        conn.commit()
