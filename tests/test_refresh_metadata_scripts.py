"""Tests for validator/refresh_paper_metadata.py and refresh_tool_metadata.py.

No network: registry answers are written into the scripts' cache files.
"""

from __future__ import annotations

import datetime as dt
import json
import sys
from pathlib import Path

import pytest
import yaml

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "validator"))

import refresh_paper_metadata as papers  # noqa: E402
import refresh_tool_metadata as tools  # noqa: E402

PAPER = """id: doe-2025-example
authors:
  - J. Doe
  - "et al."
year: 2025
title: "An Old Title"
venue: arXiv
arxiv_id: "2501.00001"
url: https://arxiv.org/abs/2501.00001
abstract: 'Some text: with a colon'
notes: >
  Kept as it is.
"""

FEED = """<?xml version='1.0' encoding='UTF-8'?>
<feed xmlns="http://www.w3.org/2005/Atom" xmlns:arxiv="http://arxiv.org/schemas/atom">
  <entry>
    <id>http://arxiv.org/abs/2501.00001v2</id>
    <updated>2025-03-01T00:00:00Z</updated>
    <published>2024-12-30T00:00:00Z</published>
    <title>A New Title:
  With a Wrapped Line</title>
    <summary>Some text: with a colon</summary>
    <author><name>Jane Doe</name></author>
    <author><name>Dan O'Malley</name></author>
    <arxiv:comment>Accepted somewhere</arxiv:comment>
  </entry>
</feed>
"""


def _paper_cache(tmp_path: Path, records: dict) -> papers.Cache:
    path = tmp_path / "cache.json"
    path.write_text(json.dumps(records), encoding="utf-8")
    return papers.Cache(path, offline=True, refetch=False)


def test_arxiv_feed_is_parsed_with_version_and_first_public_date() -> None:
    (record,) = papers.parse_arxiv_feed(FEED, "2026-11-21")
    assert record.arxiv_id == "2501.00001"
    assert record.version == "v2"
    assert record.title == "A New Title: With a Wrapped Line"
    assert record.authors == ["Jane Doe", "Dan O'Malley"]
    assert record.year == 2024  # year of v1, not of the version fetched


def test_paper_rewrite_touches_only_title_authors_year_and_version(
    tmp_path: Path,
) -> None:
    (record,) = papers.parse_arxiv_feed(FEED, "2026-11-21")
    path = tmp_path / "doe-2025-example.yml"
    path.write_text(PAPER, encoding="utf-8")
    cache = _paper_cache(tmp_path, {"arxiv:2501.00001": record.__dict__})
    plans, problems = papers.build_plans([path], cache, latest=False)
    assert not problems and not cache.errors
    assert set(plans[0].changes) == {"title", "authors", "year", "arxiv_version"}
    papers.apply(plans[0])
    after = yaml.safe_load(path.read_text(encoding="utf-8"))
    assert after["authors"] == ["Jane Doe", "Dan O'Malley"]
    assert after["title"] == "A New Title: With a Wrapped Line"
    assert after["year"] == 2024 and after["arxiv_version"] == "v2"
    before = yaml.safe_load(PAPER)
    for key in ("id", "venue", "arxiv_id", "url", "abstract", "notes"):
        assert after[key] == before[key]
    # A second look finds nothing left to change.
    plans, _ = papers.build_plans([path], cache, latest=False)
    assert plans[0].changes == {}


def test_pinned_version_is_kept_and_the_newer_one_reported(tmp_path: Path) -> None:
    (latest,) = papers.parse_arxiv_feed(FEED, "2026-11-21")
    old = dict(
        latest.__dict__, version="v1", title="An Old Title", authors=["Jane Doe"]
    )
    path = tmp_path / "doe-2025-example.yml"
    path.write_text(
        PAPER.replace(
            'arxiv_id: "2501.00001"\n', 'arxiv_id: "2501.00001"\narxiv_version: "v1"\n'
        ),
        encoding="utf-8",
    )
    cache = _paper_cache(
        tmp_path, {"arxiv:2501.00001": latest.__dict__, "arxiv:2501.00001v1": old}
    )
    plans, _ = papers.build_plans([path], cache, latest=False)
    assert "title" not in plans[0].changes and "arxiv_version" not in plans[0].changes
    assert plans[0].changes["authors"][1] == ["Jane Doe"]
    assert any("pinned to v1; arXiv has v2" in note for note in plans[0].notes)


def test_published_byline_is_kept_when_the_record_already_carries_it(
    tmp_path: Path,
) -> None:
    (arxiv,) = papers.parse_arxiv_feed(FEED, "2026-11-21")
    published = papers.Registry(
        source="crossref",
        title="A New Title: With a Wrapped Line",
        authors=["Jane Doe", "Ann Third", "Dan O'Malley"],
        first_public="2025-06-01",
        doi="10.1145/1",
    )
    text = PAPER.replace(
        '  - J. Doe\n  - "et al."\n', "  - Jane Doe\n  - Ann Third\n  - Dan O'Malley\n"
    )
    text = text.replace("venue: arXiv\n", 'venue: A Journal\ndoi: "10.1145/1"\n')
    path = tmp_path / "doe-2025-example.yml"
    path.write_text(text, encoding="utf-8")
    cache = _paper_cache(
        tmp_path,
        {"arxiv:2501.00001": arxiv.__dict__, "crossref:10.1145/1": published.__dict__},
    )
    plans, _ = papers.build_plans([path], cache, latest=False)
    assert "authors" not in plans[0].changes and "arxiv_version" not in plans[0].changes
    assert any("byline kept" in note for note in plans[0].notes)


@pytest.mark.parametrize(
    ("name", "expected"),
    [("SUNIL KOTA", "Sunil Kota"), ("Jane Doe", "Jane Doe"), ("A B", "A B")],
)
def test_crossref_names_in_capitals_are_title_cased(name: str, expected: str) -> None:
    assert papers._fix_capitals(name) == expected


@pytest.mark.parametrize(
    "name", ["Dan O'Malley", "Shi-Min Hu", "A H M Nazmus Sakib", "Yes", "Li: Wei"]
)
def test_author_names_round_trip_through_yaml(name: str) -> None:
    assert yaml.safe_load(f"- {papers.yaml_name(name)}") == [name]


def test_paper_script_refuses_other_hosts() -> None:
    with pytest.raises(ValueError):
        papers._http_get("file:///etc/hosts", "text/plain")
    with pytest.raises(ValueError):
        papers._http_get("https://example.org/x", "text/plain")


TOOL = """id: example
name: Example
description: >
  Text that stays.
first_released: 2024-01-01
last_updated: 2026-04-01
maturity_status: stable
repository_url: https://github.com/old-org/example
license: Apache-2.0
addresses_failure_modes:
  - scope_creep
stars: 10
stars_updated_at: '2026-04-23'
"""


def _tool_plan(tmp_path: Path, answer: dict, text: str = TOOL, **kwargs) -> tools.Plan:
    path = tmp_path / "example.yml"
    path.write_text(text, encoding="utf-8")
    cache_path = tmp_path / "tools.json"
    cache_path.write_text(json.dumps({"old-org/example": answer}), encoding="utf-8")
    cache = tools.Cache(cache_path, offline=True, refetch=False)
    return tools.build_plan(path, cache, dt.date(2026, 11, 21), **kwargs)


ANSWER = {
    "full_name": "new-org/example",
    "html_url": "https://github.com/new-org/example",
    "archived": True,
    "stargazers_count": 1234,
    "pushed_at": "2026-07-24T07:12:07Z",
    "license_spdx": "MIT",
    "fetched": "2026-11-21",
}


def test_archived_and_moved_repository_is_recorded_not_deleted(tmp_path: Path) -> None:
    plan = _tool_plan(tmp_path, ANSWER)
    tools.apply(plan)
    after = yaml.safe_load(plan.path.read_text(encoding="utf-8"))
    assert after["archived"] is True
    assert after["maturity_status"] == "deprecated"
    assert after["repository_url"] == "https://github.com/new-org/example"
    assert after["stars"] == 1234 and after["stars_updated_at"] == "2026-11-21"
    assert str(after["upstream_pushed_at"]) == "2026-07-24"
    assert str(after["last_updated"]) == "2026-07-24"
    assert str(after["last_reviewed"]) == "2026-11-21"
    # Tags and prose are never touched; the licence needs an explicit yes.
    assert after["addresses_failure_modes"] == ["scope_creep"]
    assert after["description"] == "Text that stays.\n"
    assert after["license"] == "Apache-2.0"
    assert any("--accept-license" in note for note in plan.notes)


def test_licence_is_written_only_for_accepted_ids(tmp_path: Path) -> None:
    plan = _tool_plan(tmp_path, ANSWER, accept_license=frozenset({"example"}))
    assert plan.changes["license"] == ("Apache-2.0", "MIT")


def test_unarchived_repository_loses_the_flag_and_status_is_left_to_an_editor(
    tmp_path: Path,
) -> None:
    text = TOOL.replace(
        "maturity_status: stable\n", "maturity_status: deprecated\narchived: true\n"
    )
    plan = _tool_plan(
        tmp_path, dict(ANSWER, archived=False, pushed_at="2026-11-20T00:00:00Z"), text
    )
    assert plan.changes["archived"] == (True, None)
    assert "maturity_status" not in plan.changes
    tools.apply(plan)
    assert "archived" not in yaml.safe_load(plan.path.read_text(encoding="utf-8"))


@pytest.mark.parametrize(
    ("current", "archived", "pushed", "expected"),
    [
        ("stable", True, "2026-11-01", "deprecated"),
        ("experimental", False, "2025-01-01", "at_risk"),
        ("stable", False, "2026-03-19", "stable"),
        ("abandoned", True, "2020-01-01", "abandoned"),
        ("at_risk", False, "2026-11-01", "at_risk"),
    ],
)
def test_status_is_only_ever_lowered(
    current: str, archived: bool, pushed: str, expected: str
) -> None:
    status, _ = tools.decide_status(
        current, archived=archived, pushed=pushed, as_of=dt.date(2026, 11, 21)
    )
    assert status == expected


def test_organisation_page_is_not_a_repository() -> None:
    assert tools.parse_repo_url("https://github.com/SocketDev") is None
    assert tools.parse_repo_url("https://github.com/astral-sh/ruff") == (
        "astral-sh",
        "ruff",
    )
    assert tools.parse_repo_url(None) is None


def test_tool_script_sends_requests_to_the_api_host_only() -> None:
    with pytest.raises(ValueError):
        tools._api_get("https://example.org/repos/a/b", "secret")
    with pytest.raises(ValueError):
        tools._api_get("file:///etc/hosts", None)
