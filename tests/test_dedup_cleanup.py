"""Unit tests for ``pipeline.cli.dedup_cleanup``.

No live Postgres: we build a minimal fake connection/cursor that
understands the narrow SQL surface the CLI uses, and we hand-craft a
``DupChecker`` by monkeypatching out its YAML loader so we can seed an
in-memory tool index.
"""

from __future__ import annotations

import json
import re
from typing import Any, Optional

import pytest

from pipeline import dedup as dedup_mod
from pipeline.cli import dedup_cleanup as dc
from pipeline.dedup import DupChecker


# ---------------------------------------------------------------------------
# Fake connection / cursor
# ---------------------------------------------------------------------------


class _FakeCursor:
    """Hand-rolled cursor that pattern-matches the SQL our CLI issues.

    We deliberately keep this narrow: it only answers the queries
    ``dedup_cleanup`` actually runs. Unknown SQL raises so a drifting
    implementation fails loud rather than silently.
    """

    def __init__(self, conn: "_FakeConn") -> None:
        self._conn = conn
        self._result: list[tuple] = []

    def execute(self, sql: str, params: tuple = ()) -> None:
        sql_norm = " ".join(sql.split())
        if "FROM candidate_tools WHERE status IN" in sql_norm and "ORDER BY id ASC" in sql_norm:
            self._result = [
                (row["id"], row["source_url"])
                for row in sorted(
                    self._conn.candidates, key=lambda r: r["id"]
                )
                if row["status"] in ("pending", "low_relevance")
            ]
            return
        if "FROM raw_search_results ORDER BY id ASC" in sql_norm:
            self._result = [
                (row["id"], row["url"])
                for row in sorted(self._conn.raw, key=lambda r: r["id"])
            ]
            return
        if sql_norm.startswith("UPDATE candidate_tools"):
            tool_id, cand_id = params
            for row in self._conn.candidates:
                if row["id"] == cand_id:
                    row["status"] = "duplicate"
                    tags = dict(row.get("nlp_tags") or {})
                    tags["dup_match"] = str(tool_id)
                    row["nlp_tags"] = tags
                    break
            self._conn.writes += 1
            return
        if sql_norm.startswith("UPDATE raw_search_results"):
            tool_id, raw_id = params
            for row in self._conn.raw:
                if row["id"] == raw_id:
                    blob = dict(row.get("raw_json") or {})
                    blob["_dup_of_yaml"] = str(tool_id)
                    row["raw_json"] = blob
                    break
            self._conn.writes += 1
            return
        if "SELECT status, COUNT(*) FROM candidate_tools GROUP BY status" in sql_norm:
            counts: dict[str, int] = {}
            for row in self._conn.candidates:
                counts[row["status"]] = counts.get(row["status"], 0) + 1
            self._result = sorted(counts.items())
            return
        if "SELECT status, COUNT(*) FROM candidate_tools WHERE id = ANY" in sql_norm:
            (ids,) = params
            id_set = set(ids)
            counts = {}
            for row in self._conn.candidates:
                if row["id"] in id_set:
                    counts[row["status"]] = counts.get(row["status"], 0) + 1
            self._result = sorted(counts.items())
            return
        raise AssertionError(f"unexpected SQL in test: {sql_norm!r}")

    def fetchall(self) -> list[tuple]:
        return list(self._result)

    def __enter__(self) -> "_FakeCursor":
        return self

    def __exit__(self, *exc: Any) -> None:
        return None


class _FakeConn:
    def __init__(
        self,
        candidates: list[dict],
        raw: Optional[list[dict]] = None,
    ) -> None:
        self.candidates = candidates
        self.raw = raw or []
        self.writes = 0
        self.commits = 0

    def cursor(self) -> _FakeCursor:
        return _FakeCursor(self)

    def commit(self) -> None:
        self.commits += 1


# ---------------------------------------------------------------------------
# DupChecker factory
# ---------------------------------------------------------------------------


def _make_checker(monkeypatch: pytest.MonkeyPatch, yaml_tools: list[dict]) -> DupChecker:
    """Build a DupChecker whose YAML index is the given in-memory list.

    Each entry: ``{"id": ..., "name": ..., "url": ...}``.
    """

    def _fake_load_yaml(self: DupChecker) -> None:
        for tool in yaml_tools:
            canon = dedup_mod.canonical_github_url(tool["url"])
            repo_key = dedup_mod.canonical_repo_key(tool["url"])
            entry = dedup_mod._IndexEntry(
                kind="yaml",
                match_id=tool["id"],
                url=canon,
                repo_key=repo_key,
                name=tool.get("name"),
                compact_name=(
                    dedup_mod._compact_name(tool["name"])
                    if tool.get("name")
                    else None
                ),
            )
            self._entries.append(entry)
            if canon:
                self._by_url.setdefault(canon, entry)
            if repo_key:
                self._by_repo_key.setdefault(repo_key, entry)

    monkeypatch.setattr(DupChecker, "_load_yaml_index", _fake_load_yaml)
    return DupChecker(yaml_dir="/nonexistent", include_candidates=False)


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


def test_marks_yaml_matches_as_duplicate(monkeypatch):
    candidates = [
        {
            "id": 100,
            "source_url": "https://github.com/Helicone/helicone",
            "status": "pending",
            "nlp_tags": {"relevance": 0.9},
        },
        {
            "id": 200,
            "source_url": "https://github.com/newthing/unseen",
            "status": "pending",
            "nlp_tags": {},
        },
    ]
    conn = _FakeConn(candidates)
    checker = _make_checker(
        monkeypatch,
        [{"id": "helicone", "name": "Helicone", "url": "https://github.com/helicone/helicone"}],
    )

    plan = dc.run(conn, checker, dry_run=False, purge_raw=False)

    assert len(plan.yaml_dups) == 1
    assert plan.yaml_dups[0].candidate_id == 100
    assert plan.yaml_dups[0].tool_id == "helicone"
    # Pre-existing nlp_tags preserved, dup_match added.
    helicone_row = next(r for r in candidates if r["id"] == 100)
    assert helicone_row["status"] == "duplicate"
    assert helicone_row["nlp_tags"]["dup_match"] == "helicone"
    assert helicone_row["nlp_tags"]["relevance"] == 0.9
    # The other row is untouched.
    other = next(r for r in candidates if r["id"] == 200)
    assert other["status"] == "pending"


def test_preserves_non_matching_pending(monkeypatch):
    candidates = [
        {
            "id": 1,
            "source_url": "https://github.com/fresh/candidate",
            "status": "pending",
            "nlp_tags": {},
        },
        {
            "id": 2,
            "source_url": "https://github.com/also/new",
            "status": "low_relevance",
            "nlp_tags": {},
        },
    ]
    conn = _FakeConn(candidates)
    checker = _make_checker(
        monkeypatch,
        [{"id": "helicone", "name": "Helicone", "url": "https://github.com/helicone/helicone"}],
    )

    plan = dc.run(conn, checker, dry_run=False, purge_raw=False)

    assert plan.yaml_dups == []
    assert plan.intra_dups == []
    assert all(r["status"] in ("pending", "low_relevance") for r in candidates)
    # No writes were issued beyond the empty apply; commit still happens.
    assert conn.writes == 0


def test_intra_batch_keeps_oldest(monkeypatch):
    # Three rows pointing at the same canonical repo; oldest (lowest id) wins.
    candidates = [
        {
            "id": 50,
            "source_url": "https://github.com/foo/bar/tree/main",
            "status": "pending",
            "nlp_tags": {},
        },
        {
            "id": 77,
            "source_url": "https://GITHUB.com/foo/bar",
            "status": "pending",
            "nlp_tags": {},
        },
        {
            "id": 120,
            "source_url": "https://github.com/foo/bar.git",
            "status": "pending",
            "nlp_tags": {},
        },
        {
            "id": 999,
            "source_url": "https://github.com/unique/repo",
            "status": "pending",
            "nlp_tags": {},
        },
    ]
    conn = _FakeConn(candidates)
    checker = _make_checker(monkeypatch, [])  # empty YAML corpus

    plan = dc.run(conn, checker, dry_run=False, purge_raw=False)

    assert plan.yaml_dups == []
    # 77 and 120 both point at keeper 50.
    ids = sorted((a.candidate_id, a.keeper_candidate_id) for a in plan.intra_dups)
    assert ids == [(77, 50), (120, 50)]

    keeper = next(r for r in candidates if r["id"] == 50)
    assert keeper["status"] == "pending"
    for cid in (77, 120):
        row = next(r for r in candidates if r["id"] == cid)
        assert row["status"] == "duplicate"
        assert row["nlp_tags"]["dup_match"] == "50"
    unique = next(r for r in candidates if r["id"] == 999)
    assert unique["status"] == "pending"


def test_dry_run_emits_report_but_no_writes(monkeypatch):
    candidates = [
        {
            "id": 100,
            "source_url": "https://github.com/Helicone/helicone",
            "status": "pending",
            "nlp_tags": {},
        },
        {
            "id": 101,
            "source_url": "https://github.com/dup/repo",
            "status": "pending",
            "nlp_tags": {},
        },
        {
            "id": 102,
            "source_url": "https://github.com/dup/repo",
            "status": "pending",
            "nlp_tags": {},
        },
    ]
    conn = _FakeConn(candidates)
    checker = _make_checker(
        monkeypatch,
        [{"id": "helicone", "name": "Helicone", "url": "https://github.com/helicone/helicone"}],
    )

    plan = dc.run(conn, checker, dry_run=True, purge_raw=False)

    # Dry-run: DB untouched, no writes, no commits.
    assert conn.writes == 0
    assert conn.commits == 0
    assert all(r["status"] == "pending" for r in candidates)

    # But the plan populates and the report renders.
    assert len(plan.yaml_dups) == 1
    assert len(plan.intra_dups) == 1
    report = dc.format_report(plan, dry_run=True, include_raw=False)
    assert "[dry-run]" in report
    assert "helicone" in report
    # Projected final counts show 2 duplicates even though we didn't write.
    assert plan.final_status_counts.get("duplicate", 0) == 2
    # Original pending count was 3; 2 leaving -> 1 pending projected.
    assert plan.final_status_counts.get("pending", 0) == 1


def test_purge_raw_tags_raw_json(monkeypatch):
    candidates: list[dict] = []
    raw = [
        {
            "id": 10,
            "url": "https://github.com/Helicone/helicone",
            "raw_json": {"query": "q", "result": {"x": 1}},
        },
        {
            "id": 11,
            "url": "https://github.com/unrelated/thing",
            "raw_json": {"query": "q"},
        },
    ]
    conn = _FakeConn(candidates, raw=raw)
    checker = _make_checker(
        monkeypatch,
        [{"id": "helicone", "name": "Helicone", "url": "https://github.com/helicone/helicone"}],
    )

    plan = dc.run(conn, checker, dry_run=False, purge_raw=True)

    assert len(plan.raw_dups) == 1
    assert plan.raw_dups[0].raw_id == 10
    assert plan.raw_dups[0].tool_id == "helicone"
    # The tagged row kept its original payload and gained _dup_of_yaml.
    helicone_raw = next(r for r in raw if r["id"] == 10)
    assert helicone_raw["raw_json"]["_dup_of_yaml"] == "helicone"
    assert helicone_raw["raw_json"]["query"] == "q"
    # Unmatched raw row untouched.
    other_raw = next(r for r in raw if r["id"] == 11)
    assert "_dup_of_yaml" not in other_raw["raw_json"]


def test_purge_raw_off_by_default(monkeypatch):
    candidates: list[dict] = []
    raw = [
        {
            "id": 10,
            "url": "https://github.com/Helicone/helicone",
            "raw_json": {"query": "q"},
        }
    ]
    conn = _FakeConn(candidates, raw=raw)
    checker = _make_checker(
        monkeypatch,
        [{"id": "helicone", "name": "Helicone", "url": "https://github.com/helicone/helicone"}],
    )

    plan = dc.run(conn, checker, dry_run=False, purge_raw=False)
    assert plan.raw_dups == []
    assert "_dup_of_yaml" not in raw[0]["raw_json"]


def test_skipped_rows_are_not_scanned(monkeypatch):
    # status='skipped' should be invisible to the cleanup (scope is strictly
    # 'pending' and 'low_relevance').
    candidates = [
        {
            "id": 1,
            "source_url": "https://github.com/Helicone/helicone",
            "status": "skipped",
            "nlp_tags": {},
        },
        {
            "id": 2,
            "source_url": "https://github.com/Helicone/helicone",
            "status": "pending",
            "nlp_tags": {},
        },
    ]
    conn = _FakeConn(candidates)
    checker = _make_checker(
        monkeypatch,
        [{"id": "helicone", "name": "Helicone", "url": "https://github.com/helicone/helicone"}],
    )

    plan = dc.run(conn, checker, dry_run=False, purge_raw=False)
    # Only id=2 is visible and it matches the YAML; the 'skipped' row is left
    # alone even though it also points at helicone.
    assert [a.candidate_id for a in plan.yaml_dups] == [2]
    assert candidates[0]["status"] == "skipped"  # still skipped
    assert candidates[1]["status"] == "duplicate"


def test_format_report_contains_per_tool_breakdown(monkeypatch):
    candidates = [
        {
            "id": 100,
            "source_url": "https://github.com/Helicone/helicone",
            "status": "pending",
            "nlp_tags": {},
        },
        {
            "id": 101,
            "source_url": "https://github.com/foo/aider",
            "status": "pending",
            "nlp_tags": {},
        },
    ]
    conn = _FakeConn(candidates)
    checker = _make_checker(
        monkeypatch,
        [
            {"id": "helicone", "name": "Helicone", "url": "https://github.com/helicone/helicone"},
            {"id": "aider", "name": "Aider", "url": "https://github.com/foo/aider"},
        ],
    )
    plan = dc.run(conn, checker, dry_run=True, purge_raw=False)
    report = dc.format_report(plan, dry_run=True, include_raw=False)
    assert "helicone: 1" in report
    assert "aider: 1" in report
    assert "YAML-matched candidates: 2" in report
