"""End-to-end smoke test for pipeline.db against a live Postgres.

It drops and re-creates the five pipeline tables, so it runs only against
a database whose name contains ``_test``:

    createdb saica_kg_test
    POSTGRES_URL=postgresql://saica:saica_local_dev@localhost:5432/saica_kg_test \\
        .venv/bin/python -m pytest tests/test_db_smoke.py -q

With any other ``POSTGRES_URL`` (for example the staging database in
``.env.local``, which holds the only copy of the April 2026 extractions)
the round-trip test is skipped and nothing is touched. The guard tests in
this file need no database at all.
"""

from __future__ import annotations

import sys

import pytest

from pipeline import db


def _use_dsn(monkeypatch: pytest.MonkeyPatch, dsn: str) -> None:
    monkeypatch.setattr(db, "_dsn", lambda: dsn)


def test_target_never_shows_credentials(monkeypatch: pytest.MonkeyPatch) -> None:
    _use_dsn(monkeypatch, "postgresql://someone:s3cret@db.example:6543/saica_kg")
    assert db.describe_target() == "db.example:6543/saica_kg"
    assert (
        "s3cret" not in db.describe_target() and "someone" not in db.describe_target()
    )
    assert db.is_test_database() is False
    _use_dsn(monkeypatch, "postgresql://someone:s3cret@db.example:6543/saica_kg_test")
    assert db.is_test_database() is True
    _use_dsn(monkeypatch, "host=h port=1 dbname=x_test_2 user=u password=p")
    assert db.describe_target() == "h:1/x_test_2" and db.is_test_database()


def test_drop_first_is_refused_outside_a_test_database(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The refusal comes before any connection is opened."""
    _use_dsn(monkeypatch, "postgresql://u:p@localhost:5432/saica_kg")

    def no_connection(*_args, **_kwargs):
        raise AssertionError("init_schema connected to a non-test database")

    monkeypatch.setattr(db.psycopg, "connect", no_connection)
    with pytest.raises(db.RefusedDrop, match="localhost:5432/saica_kg"):
        db.init_schema(drop_first=True)


def test_cli_drop_first_prints_the_target_and_needs_yes(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture
) -> None:
    from pipeline.cli import db as db_cli

    _use_dsn(monkeypatch, "postgresql://u:p@localhost:5432/saica_kg")
    calls: list[dict] = []
    monkeypatch.setattr(db, "init_schema", lambda **kwargs: calls.append(kwargs))

    assert db_cli.main(["init", "--drop-first"]) == 2
    out = capsys.readouterr()
    assert "target database: localhost:5432/saica_kg" in out.out
    assert "--yes" in out.err
    assert calls == [], "nothing may run without --yes"

    assert db_cli.main(["init", "--drop-first", "--yes"]) == 0
    assert calls == [{"drop_first": True, "allow_non_test": True}]

    calls.clear()
    assert db_cli.main(["init"]) == 0
    assert calls == [{"drop_first": False, "allow_non_test": False}]


def test_db_roundtrip() -> None:
    """Insert, upsert and read back through every helper. Needs a database
    whose name contains ``_test``; skipped otherwise."""
    if not db.is_test_database():
        pytest.skip(
            f"POSTGRES_URL points at {db.describe_target()}, not a *_test"
            " database; the round trip drops tables and is not run there"
        )
    try:
        with db.get_conn():
            pass
    except db.psycopg.OperationalError as exc:
        pytest.skip(f"test database not reachable: {str(exc).splitlines()[0]}")
    assert run() == 0


def run() -> int:
    # Re-init from scratch so counts are predictable. init_schema refuses
    # to drop the tables of a database whose name lacks "_test".
    db.init_schema(drop_first=True)

    # --- raw_search_results ---
    rid = db.insert_raw_result(
        "perplexity",
        "ai coding agent supervision tools",
        url="https://example.com/tool-x",
        title="Tool X",
        snippet="A supervision layer for coding agents.",
        raw_json={"source": "perplexity", "ranked": 1, "score": 0.91},
    )
    assert rid is not None, "expected an id on first insert"

    # Duplicate (same source + url + title -> same content_hash) should be skipped.
    dup = db.insert_raw_result(
        "perplexity",
        "ai coding agent supervision tools",
        url="https://example.com/tool-x",
        title="Tool X",
        snippet="irrelevant; dedupe is over url+title",
        raw_json={"duplicate": True},
    )
    assert dup is None, f"expected duplicate insert to return None, got {dup!r}"

    rows = db.raw_results_by_query("perplexity", "ai coding agent supervision tools")
    assert len(rows) == 1, f"expected 1 row, got {len(rows)}"
    assert rows[0]["title"] == "Tool X"
    assert rows[0]["raw_json"]["score"] == 0.91

    # --- raw_readmes ---
    db.insert_readme("https://github.com/owner/tool-x", "# Tool X\n\nReadme body.")
    db.insert_readme("https://github.com/owner/tool-x", "# Tool X\n\nUpdated body.")

    # --- candidate_tools ---
    cid = db.upsert_candidate_tool(
        source_url="https://github.com/owner/tool-x",
        proposed_id="tool-x",
        name="Tool X",
        summary="Supervision layer for coding agents.",
        nlp_tags={
            "keywords": ["supervision", "agent"],
            "failure_modes": ["fabrication"],
        },
    )
    assert isinstance(cid, int) and cid > 0

    cid2 = db.upsert_candidate_tool(
        source_url="https://github.com/owner/tool-x",
        extracted={"tagline": "Guardrails for agents", "confidence": {"tagline": 0.82}},
    )
    assert cid2 == cid, f"upsert should return same id; got {cid2} vs {cid}"

    pending = db.get_pending("tools", limit=10)
    assert len(pending) == 1
    assert pending[0]["proposed_id"] == "tool-x"
    assert pending[0]["extracted"]["tagline"] == "Guardrails for agents"
    # nlp_tags survived the second upsert (extracted-only) thanks to CASE guard.
    assert pending[0]["nlp_tags"]["failure_modes"] == ["fabrication"]

    db.update_candidate_status("tools", cid, "reviewed", reviewer="vasyl")
    still_pending = db.get_pending("tools")
    assert len(still_pending) == 0

    # --- candidate_papers ---
    pid = db.upsert_candidate_paper(
        source_url="https://arxiv.org/abs/2603.01234",
        proposed_id="smith-2026-supervision",
        title="Supervising Coding Agents at Scale",
        authors=["Smith, A.", "Lee, B."],
        year=2026,
        arxiv_id="2603.01234",
    )
    assert isinstance(pid, int) and pid > 0
    papers_pending = db.get_pending("papers")
    assert len(papers_pending) == 1
    assert papers_pending[0]["authors"] == ["Smith, A.", "Lee, B."]

    print("smoke test OK")
    for name, count in db.table_counts():
        print(f"  {name:25s} count={count}")
    return 0


if __name__ == "__main__":
    if not db.is_test_database():
        sys.exit(
            f"not run: POSTGRES_URL points at {db.describe_target()}, and this"
            " smoke test drops tables. Use a database whose name contains"
            " '_test'."
        )
    sys.exit(run())
