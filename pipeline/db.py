"""Postgres connection + helpers for the SAICA-KG ingestion pipeline.

This module is the contract that all other pipeline modules depend on; keep
the public API stable. Uses psycopg 3 (NOT psycopg2) and JSONB via
``psycopg.types.json.Json``.

Environment:
    POSTGRES_URL  DSN; defaults to the local docker-compose instance.
"""

from __future__ import annotations

import os
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterator, Optional

import psycopg
from psycopg.rows import dict_row
from psycopg.types.json import Json

_DEFAULT_DSN = "postgresql://saica:saica_local_dev@localhost:5433/saica_kg"

_SCHEMA_PATH = Path(__file__).with_name("schema.sql")

# Order matters for drop (children -> parents isn't needed here since there are
# no FKs, but we still list them explicitly so ``drop_first=True`` is
# deterministic).
_TABLES = (
    "raw_search_results",
    "raw_readmes",
    "candidate_tools",
    "candidate_papers",
    "candidate_incidents",
)

_CANDIDATE_KIND_TO_TABLE = {
    "tools": "candidate_tools",
    "papers": "candidate_papers",
    "incidents": "candidate_incidents",
}


def _dsn() -> str:
    return os.environ.get("POSTGRES_URL", _DEFAULT_DSN)


@contextmanager
def get_conn() -> Iterator[psycopg.Connection]:
    """Yield a psycopg connection; caller must commit/rollback."""
    conn = psycopg.connect(_dsn())
    try:
        yield conn
    finally:
        conn.close()


def init_schema(drop_first: bool = False) -> None:
    """Run ``schema.sql`` against the configured DB.

    If ``drop_first`` is true, existing pipeline tables are dropped first so
    the schema can be re-applied from scratch (useful in tests).
    """
    ddl = _SCHEMA_PATH.read_text()
    with get_conn() as conn, conn.cursor() as cur:
        if drop_first:
            for table in _TABLES:
                cur.execute(f"DROP TABLE IF EXISTS {table} CASCADE;")
        cur.execute(ddl)
        conn.commit()


def _table_for(kind: str) -> str:
    try:
        return _CANDIDATE_KIND_TO_TABLE[kind]
    except KeyError as exc:
        raise ValueError(
            f"Unknown candidate kind {kind!r}; expected one of "
            f"{sorted(_CANDIDATE_KIND_TO_TABLE)}"
        ) from exc


# ---------------------------------------------------------------------------
# raw_search_results
# ---------------------------------------------------------------------------


def insert_raw_result(
    source: str,
    query: str,
    *,
    url: Optional[str] = None,
    title: Optional[str] = None,
    snippet: Optional[str] = None,
    raw_json: Any,
) -> Optional[int]:
    """Insert a raw search result.

    Returns the new row id, or ``None`` if a row with the same
    ``(source, content_hash)`` already exists (duplicate skipped). The
    ``content_hash`` is a generated column over ``md5(url || title)``.
    """
    sql = """
        INSERT INTO raw_search_results (source, query, url, title, snippet, raw_json)
        VALUES (%s, %s, %s, %s, %s, %s)
        ON CONFLICT (source, content_hash) DO NOTHING
        RETURNING id
    """
    with get_conn() as conn, conn.cursor() as cur:
        cur.execute(sql, (source, query, url, title, snippet, Json(raw_json)))
        row = cur.fetchone()
        conn.commit()
        return row[0] if row else None


def raw_results_by_query(source: str, query: str) -> list[dict]:
    """Return every raw_search_results row for a given ``(source, query)``."""
    sql = """
        SELECT id, source, query, url, title, snippet, raw_json,
               fetched_at, content_hash
        FROM raw_search_results
        WHERE source = %s AND query = %s
        ORDER BY fetched_at DESC
    """
    with get_conn() as conn, conn.cursor(row_factory=dict_row) as cur:
        cur.execute(sql, (source, query))
        return list(cur.fetchall())


# ---------------------------------------------------------------------------
# raw_readmes
# ---------------------------------------------------------------------------


def insert_readme(url: str, content: str) -> None:
    """Upsert a README by url; updates content + fetched_at on conflict."""
    sql = """
        INSERT INTO raw_readmes (url, content)
        VALUES (%s, %s)
        ON CONFLICT (url) DO UPDATE
        SET content    = EXCLUDED.content,
            fetched_at = NOW()
    """
    with get_conn() as conn, conn.cursor() as cur:
        cur.execute(sql, (url, content))
        conn.commit()


# ---------------------------------------------------------------------------
# candidate_tools
# ---------------------------------------------------------------------------


def upsert_candidate_tool(
    *,
    source_url: str,
    proposed_id: Optional[str] = None,
    name: Optional[str] = None,
    summary: Optional[str] = None,
    extracted: Optional[dict] = None,
    nlp_tags: Optional[dict] = None,
) -> int:
    """Insert or update-by-source_url; returns candidate_id.

    Only non-None fields overwrite existing values on conflict — so a cheap
    NLP pre-pass that only sets ``nlp_tags`` won't clobber a later Azure
    extraction that sets ``extracted``.
    """
    # Note: %s::jsonb casts are required because psycopg's Json adapter binds
    # as PG type ``json`` (not ``jsonb``); COALESCE then can't unify with a
    # ``'{}'::jsonb`` literal.
    sql = """
        INSERT INTO candidate_tools (source_url, proposed_id, name, summary, extracted, nlp_tags)
        VALUES (
            %s, %s, %s, %s,
            COALESCE(%s::jsonb, '{}'::jsonb),
            COALESCE(%s::jsonb, '{}'::jsonb)
        )
        ON CONFLICT (source_url) DO UPDATE SET
            proposed_id = COALESCE(EXCLUDED.proposed_id, candidate_tools.proposed_id),
            name        = COALESCE(EXCLUDED.name,        candidate_tools.name),
            summary     = COALESCE(EXCLUDED.summary,     candidate_tools.summary),
            extracted   = CASE WHEN %s::jsonb IS NULL THEN candidate_tools.extracted ELSE EXCLUDED.extracted END,
            nlp_tags    = CASE WHEN %s::jsonb IS NULL THEN candidate_tools.nlp_tags  ELSE EXCLUDED.nlp_tags  END
        RETURNING id
    """
    extracted_j = Json(extracted) if extracted is not None else None
    nlp_tags_j = Json(nlp_tags) if nlp_tags is not None else None
    with get_conn() as conn, conn.cursor() as cur:
        cur.execute(
            sql,
            (
                source_url,
                proposed_id,
                name,
                summary,
                extracted_j,
                nlp_tags_j,
                extracted_j,
                nlp_tags_j,
            ),
        )
        row = cur.fetchone()
        conn.commit()
        assert row is not None
        return row[0]


# ---------------------------------------------------------------------------
# candidate_papers
# ---------------------------------------------------------------------------


def upsert_candidate_paper(
    *,
    source_url: str,
    proposed_id: Optional[str] = None,
    title: Optional[str] = None,
    authors: Optional[list[str]] = None,
    year: Optional[int] = None,
    venue: Optional[str] = None,
    doi: Optional[str] = None,
    arxiv_id: Optional[str] = None,
    extracted: Optional[dict] = None,
    nlp_tags: Optional[dict] = None,
) -> int:
    """Insert or update-by-source_url; returns candidate_id."""
    # See note in upsert_candidate_tool re: %s::jsonb casts.
    sql = """
        INSERT INTO candidate_papers (
            source_url, proposed_id, title, authors, year, venue,
            doi, arxiv_id, extracted, nlp_tags
        )
        VALUES (
            %s, %s, %s, %s, %s, %s, %s, %s,
            COALESCE(%s::jsonb, '{}'::jsonb),
            COALESCE(%s::jsonb, '{}'::jsonb)
        )
        ON CONFLICT (source_url) DO UPDATE SET
            proposed_id = COALESCE(EXCLUDED.proposed_id, candidate_papers.proposed_id),
            title       = COALESCE(EXCLUDED.title,       candidate_papers.title),
            authors     = COALESCE(EXCLUDED.authors,     candidate_papers.authors),
            year        = COALESCE(EXCLUDED.year,        candidate_papers.year),
            venue       = COALESCE(EXCLUDED.venue,       candidate_papers.venue),
            doi         = COALESCE(EXCLUDED.doi,         candidate_papers.doi),
            arxiv_id    = COALESCE(EXCLUDED.arxiv_id,    candidate_papers.arxiv_id),
            extracted   = CASE WHEN %s::jsonb IS NULL THEN candidate_papers.extracted ELSE EXCLUDED.extracted END,
            nlp_tags    = CASE WHEN %s::jsonb IS NULL THEN candidate_papers.nlp_tags  ELSE EXCLUDED.nlp_tags  END
        RETURNING id
    """
    extracted_j = Json(extracted) if extracted is not None else None
    nlp_tags_j = Json(nlp_tags) if nlp_tags is not None else None
    with get_conn() as conn, conn.cursor() as cur:
        cur.execute(
            sql,
            (
                source_url,
                proposed_id,
                title,
                authors,
                year,
                venue,
                doi,
                arxiv_id,
                extracted_j,
                nlp_tags_j,
                extracted_j,
                nlp_tags_j,
            ),
        )
        row = cur.fetchone()
        conn.commit()
        assert row is not None
        return row[0]


# ---------------------------------------------------------------------------
# candidate queue inspection / status
# ---------------------------------------------------------------------------


def get_pending(kind: str, limit: int = 100) -> list[dict]:
    """Return ``status='pending'`` rows for one of ``tools|papers|incidents``."""
    table = _table_for(kind)
    sql = f"""
        SELECT *
        FROM {table}
        WHERE status = 'pending'
        ORDER BY created_at ASC
        LIMIT %s
    """
    with get_conn() as conn, conn.cursor(row_factory=dict_row) as cur:
        cur.execute(sql, (limit,))
        return list(cur.fetchall())


def update_candidate_status(
    kind: str,
    candidate_id: int,
    status: str,
    reviewer: Optional[str] = None,
    graduated_to: Optional[str] = None,
) -> None:
    """Transition a candidate to a new status.

    ``candidate_incidents`` has no ``reviewed_at``/``reviewer`` columns, so
    those updates are only applied to tools/papers.
    """
    table = _table_for(kind)
    if table == "candidate_incidents":
        sql = f"""
            UPDATE {table}
            SET status = %s,
                graduated_to = COALESCE(%s, graduated_to)
            WHERE id = %s
        """
        params: tuple = (status, graduated_to, candidate_id)
    else:
        sql = f"""
            UPDATE {table}
            SET status       = %s,
                reviewer     = COALESCE(%s, reviewer),
                reviewed_at  = CASE WHEN %s IN ('reviewed', 'accepted', 'rejected', 'graduated')
                                    THEN NOW() ELSE reviewed_at END,
                graduated_to = COALESCE(%s, graduated_to)
            WHERE id = %s
        """
        params = (status, reviewer, status, graduated_to, candidate_id)
    with get_conn() as conn, conn.cursor() as cur:
        cur.execute(sql, params)
        conn.commit()


# ---------------------------------------------------------------------------
# status / diagnostics
# ---------------------------------------------------------------------------


def table_counts() -> list[tuple[str, int]]:
    """Return ``[(table_name, row_count), ...]`` for each pipeline table."""
    out: list[tuple[str, int]] = []
    with get_conn() as conn, conn.cursor() as cur:
        for table in _TABLES:
            cur.execute(f"SELECT COUNT(*) FROM {table}")
            row = cur.fetchone()
            out.append((table, int(row[0]) if row else 0))
    return out
