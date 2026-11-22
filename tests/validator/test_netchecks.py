"""The opt-in network checks (``validator/cli.py --arxiv`` / ``--links``).

No test here opens a socket: the arXiv check reads a prepared cache with
``offline=True`` and the link check gets a fake prober.
"""

from __future__ import annotations

import datetime as dt
import json
import sys
from pathlib import Path
from typing import Any

from kg_fixture import edit_yaml, run_gate
from validator import cli as validator_cli
from validator import netchecks as nc

FEED = """<?xml version="1.0" encoding="UTF-8"?>
<feed xmlns="http://www.w3.org/2005/Atom">
  <entry>
    <id>http://arxiv.org/abs/2503.13657v3</id>
    <published>2025-03-17T19:04:38Z</published>
    <title>Why Do Multi-Agent LLM
      Systems Fail?</title>
    <author><name>Mert Cemri</name></author>
    <author><name>Melissa Z. Pan</name></author>
  </entry>
  <entry><title>Error</title></entry>
</feed>
"""


def _records(
    tmp_path: Path, records: dict[str, Any], latest: dict[str, str]
) -> nc.ArxivRecords:
    path = tmp_path / "arxiv_records.json"
    path.write_text(
        json.dumps(
            {
                "records": records,
                "latest": {
                    k: {"version": v, "checked": "2026-11-21"}
                    for k, v in latest.items()
                },
            }
        )
    )
    return nc.ArxivRecords(path, offline=True)


def _paper(name: str, **fields: Any) -> tuple[Path, dict[str, Any]]:
    return Path(f"papers/{name}.yml"), {"id": name, **fields}


def test_parse_arxiv_feed_reads_id_version_title_and_authors() -> None:
    records = nc.parse_arxiv_feed(FEED)
    assert records == [
        {
            "id": "2503.13657",
            "version": "v3",
            "title": "Why Do Multi-Agent LLM Systems Fail?",
            "authors": ["Mert Cemri", "Melissa Z. Pan"],
            "published": "2025-03-17",
        }
    ]


def test_title_and_first_author_are_compared_with_the_cached_record(
    tmp_path: Path,
) -> None:
    records = _records(
        tmp_path,
        {
            "2507.03525v2": {
                "title": "Limits of Safe AI Deployment: Differentiating Oversight and Control",
                "authors": ["David Manheim", "Aidan Homewood"],
            },
            "2503.13657v3": {
                "title": "Why Do Multi-Agent LLM Systems Fail?",
                "authors": ["Mert Cemri", "Melissa Z. Pan"],
            },
        },
        {"2507.03525": "v2", "2503.13657": "v3"},
    )
    nodes = {
        "papers": [
            _paper(
                "wrong-title",
                arxiv_id="2507.03525",
                title="Distinguishing Control and Oversight in Agentic AI",
                authors=["David Manheim", "James Homewood"],
            ),
            _paper(
                "wrong-first-author",
                arxiv_id="2503.13657",
                title="Why do multi-agent LLM systems fail",
                authors=["Melissa Pan", "Mert Cemri"],
            ),
            _paper(
                "fine",
                arxiv_id="arXiv:2503.13657v3",
                title="Why Do Multi-Agent LLM Systems Fail?",
                authors=["Mért Cemri"],
            ),
        ]
    }
    errors, warnings, notes = nc.check_arxiv(nodes, records)
    assert len(errors) == 2, errors
    assert "wrong-title.yml :: title" in errors[0]
    assert "Limits of Safe AI Deployment" in errors[0]
    assert "wrong-first-author.yml :: authors/0" in errors[1]
    assert warnings == [] and notes == []


def test_named_version_means_the_whole_byline_is_compared(tmp_path: Path) -> None:
    records = _records(
        tmp_path,
        {
            "2507.03525v2": {
                "title": "Limits of Safe AI Deployment",
                "authors": ["David Manheim", "Aidan Homewood"],
            }
        },
        {},
    )

    def paper(authors: list[str]) -> dict[str, Any]:
        return {
            "papers": [
                _paper(
                    "p",
                    arxiv_id="2507.03525",
                    arxiv_version="v2",
                    title="Limits of Safe AI Deployment",
                    authors=authors,
                )
            ]
        }

    assert nc.check_arxiv(paper(["David Manheim", "Aidan Homewood"]), records)[0] == []
    wrong_name = nc.check_arxiv(paper(["David Manheim", "James Homewood"]), records)[0]
    assert len(wrong_name) == 1 and "authors/1 — 'James Homewood'" in wrong_name[0]
    missing = nc.check_arxiv(paper(["David Manheim"]), records)[0]
    assert len(missing) == 1 and "1 names, but arXiv 2507.03525v2 has 2" in missing[0]


def test_arxiv_link_in_incident_must_share_words_with_the_incident(
    tmp_path: Path,
) -> None:
    records = _records(
        tmp_path,
        {
            "2406.08291v1": {
                "title": "Collective Invasion: When does domain curvature matter?",
                "authors": ["J. Pollacco"],
            },
            "2406.09834v2": {
                "title": "LLMs Meet Library Evolution: Evaluating Deprecated API Usage in LLM-based Code Completion",
                "authors": ["Chong Wang"],
            },
        },
        {"2406.08291": "v1", "2406.09834": "v2"},
    )
    incident = {
        "id": "copilot-obsolete-api",
        "title": "Code LLMs emit deprecated library APIs",
        "description": "A study of code completion found deprecated API usage across libraries.",
    }
    wrong = {
        "incidents": [
            (
                Path("incidents/x.yml"),
                {**incident, "source_urls": ["https://arxiv.org/abs/2406.08291"]},
            )
        ]
    }
    right = {
        "incidents": [
            (
                Path("incidents/x.yml"),
                {**incident, "source_urls": ["https://arxiv.org/abs/2406.09834v2"]},
            )
        ]
    }
    errors = nc.check_arxiv(wrong, records)[0]
    assert (
        len(errors) == 1
        and "Collective Invasion" in errors[0]
        and "wrong arXiv id?" in errors[0]
    )
    assert nc.check_arxiv(right, records)[0] == []


def test_offline_without_a_cached_record_is_a_note_not_an_error(tmp_path: Path) -> None:
    records = _records(tmp_path, {}, {})
    nodes = {"papers": [_paper("p", arxiv_id="2501.00001", title="T", authors=["A B"])]}
    errors, warnings, notes = nc.check_arxiv(nodes, records)
    assert errors == [] and warnings == []
    assert (
        notes and "1 paper(s) with an arxiv_id have no cached arXiv record" in notes[0]
    )
    assert not (tmp_path / "arxiv_records.json").read_text().count("2501.00001")


def test_malformed_arxiv_id_is_an_error(tmp_path: Path) -> None:
    records = _records(tmp_path, {}, {})
    nodes = {"papers": [_paper("p", arxiv_id="not-an-id", title="T", authors=["A B"])]}
    errors = nc.check_arxiv(nodes, records)[0]
    assert len(errors) == 1 and "is not an arXiv identifier" in errors[0]


# --- links -----------------------------------------------------------------


def _link_nodes() -> dict[str, Any]:
    return {
        "incidents": [
            (
                Path("incidents/i.yml"),
                {
                    "id": "i",
                    "source_urls": [
                        "https://example.org/gone",
                        "https://example.org/blocked",
                        "https://example.org/blog/post",
                        "https://example.org/fine",
                    ],
                },
            )
        ],
        "tools": [
            (
                Path("tools/t.yml"),
                {"id": "t", "documentation_url": "https://x.dev/docs"},
            )
        ],
    }


def _fake_prober(calls: list[str]):
    answers = {
        "https://example.org/gone": {
            "status": 404,
            "final": "https://example.org/gone",
        },
        "https://example.org/blocked": {
            "status": 403,
            "final": "https://example.org/blocked",
        },
        "https://example.org/blog/post": {
            "status": 200,
            "final": "https://www.example.org/",
        },
        "https://example.org/fine": {
            "status": 200,
            "final": "https://example.org/fine",
        },
        "https://x.dev/docs": {"status": 200, "final": "https://docs.x.dev/"},
    }

    def prober(url: str) -> dict[str, Any]:
        calls.append(url)
        return dict(answers[url])

    return prober


def test_link_check_classifies_and_caches(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(nc.time, "sleep", lambda _s: None)
    cache = tmp_path / "links.json"
    calls: list[str] = []
    today = dt.date(2026, 11, 21)
    errors, warnings, notes = nc.check_links(
        _link_nodes(), cache_path=cache, today=today, prober=_fake_prober(calls)
    )
    assert (
        len(errors) == 1
        and "https://example.org/gone answers 404 (dead link)" in errors[0]
    )
    assert "[incidents] i.yml :: source_urls/0" in errors[0]
    assert any("could not be verified (status 403)" in w for w in warnings)
    assert any(
        "https://example.org/blog/post now redirects to a home page" in w
        for w in warnings
    )
    assert not any(
        "x.dev" in w for w in warnings
    ), "a move to a docs sub-domain is fine"
    assert len(warnings) == 2
    assert notes == ["link check: 5 distinct URLs, 0 not checked"]
    assert len(calls) == 5

    # Same day: good answers come from the cache, failures are asked again
    # only after a day.
    calls.clear()
    again = nc.check_links(
        _link_nodes(), cache_path=cache, today=today, prober=_fake_prober(calls)
    )
    assert calls == [] and again[0] == errors

    # Offline with an empty cache: nothing is requested, nothing is claimed.
    calls.clear()
    offline = nc.check_links(
        _link_nodes(),
        offline=True,
        cache_path=tmp_path / "empty.json",
        today=today,
        prober=_fake_prober(calls),
    )
    assert calls == []
    assert offline == ([], [], ["link check: 5 distinct URLs, 5 not checked"])


# --- CLI wiring --------------------------------------------------------------


def test_default_gate_does_not_load_the_network_module(kg: Path, monkeypatch) -> None:
    monkeypatch.delitem(sys.modules, "validator.netchecks", raising=False)
    monkeypatch.delattr(validator_cli, "netchecks", raising=False)
    code, _ = run_gate(kg)
    assert code == 0
    assert "validator.netchecks" not in sys.modules


def test_arxiv_flag_reports_through_the_gate(
    kg: Path, tmp_path: Path, monkeypatch
) -> None:
    cache = tmp_path / "arxiv_records.json"
    cache.write_text(
        json.dumps(
            {
                "records": {
                    "2501.00001v2": {
                        "title": "A Completely Different Paper",
                        "authors": ["Ada Lovelace", "Alan Turing"],
                    }
                },
                "latest": {},
            }
        )
    )
    monkeypatch.setattr(nc, "ARXIV_CACHE", cache)
    code, output = run_gate(kg, "--arxiv", "--offline")
    assert code == 1
    assert "paper-a.yml :: title" in output and "A Completely Different Paper" in output

    edit_yaml(
        kg / "papers" / "paper-a.yml",
        lambda d: d.update(title="A completely different paper"),
    )
    code, output = run_gate(kg, "--arxiv", "--offline")
    assert code == 0, output
