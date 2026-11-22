"""Tests for the results report: bench/build_report.py and the modules it is made of.

Run: .venv/bin/python -m pytest tests/bench_report -q

They read only tracked files (bench/<mode>/published/, bench/kitbuilder/*.json, data/tools/*.yml), never the raw
caches, and make no model call. One full build is shared by the tests of this module (about 7 seconds).
"""

from __future__ import annotations

import json
import re
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
BENCH = REPO / "bench"
sys.path.insert(0, str(BENCH))

import build_report  # noqa: E402
import report_findings  # noqa: E402
import report_page  # noqa: E402
import report_rules as R  # noqa: E402
import report_stats  # noqa: E402

TRACKED = REPO / "site" / "public" / "bench" / "results.json"


@pytest.fixture(scope="module")
def built():
    results, kit, src = build_report.build(BENCH)
    return (
        json.loads(build_report.dump(results)),
        json.loads(build_report.dump(kit)),
        src,
    )


def shadow(tmp_path: Path) -> Path:
    """A copy of the tracked inputs only: what a clean clone has."""
    bench = tmp_path / "bench"
    for d in sorted(BENCH.glob("*/published")):
        shutil.copytree(d, bench / d.parent.name / "published")
    (bench / "kitbuilder").mkdir(parents=True)
    for name in ("recipes.json", "pairs.json", "star_modes.json"):
        shutil.copy(BENCH / "kitbuilder" / name, bench / "kitbuilder" / name)
    shutil.copytree(REPO / "data" / "tools", tmp_path / "data" / "tools")
    return bench


# ------------------------------------------------------------------------------------------- shape of the output
def test_keys_the_site_and_kit_read_are_still_there(built):
    """results.json stays additive: every key a consumer read before this version is present, with its old type."""
    res, kit, _ = built
    assert re.fullmatch(
        r"\d{4}-\d{2}-\d{2}", res["generated"]
    )  # bench.ts: new Date(generated + 'T00:00:00Z')
    assert set(res["type_label"]) >= {
        "deterministic",
        "llm_based",
        "hybrid",
        "baseline_model",
        "baseline_rule",
    }
    assert isinstance(res["star_modes"], list)
    for m in res["modes"]:
        for k in (
            "id",
            "name",
            "n",
            "n_pos",
            "n_neg",
            "pos_label",
            "dataset",
            "summary",
            "setup",
            "caveats",
            "rows",
        ):
            assert k in m, (m.get("id"), k)
        assert all(isinstance(s, str) for s in m["setup"] + m["caveats"])
        for r in m["rows"]:
            for k in (
                "key",
                "tool",
                "type",
                "j",
                "catch",
                "catch_ci",
                "fa",
                "fa_ci",
                "cost",
                "cost_note",
            ):
                assert k in r, (m["id"], r.get("key"), k)
            assert r["type"] in res["type_label"]
            assert isinstance(r["j"], float) and isinstance(r["cost"], float)
            assert abs(r["j"] - (r["catch"] - r["fa"])) < 2e-6
    ov = res["overview"]
    assert {"modes", "rows", "best", "findings", "caveats"} <= set(ov)
    assert all(
        len(f) == 2 and all(isinstance(x, str) for x in f) for f in ov["findings"]
    )
    for row in ov["rows"]:
        assert {"tool", "type", "cells", "avg", "n_modes"} <= set(row)
        for c in row["cells"].values():
            assert {"j", "tool", "short", "fa", "cost1k"} <= set(c)
    for b in ov["best"].values():
        assert {"j", "tool", "short", "type"} <= set(b)
    assert {m["id"] for m in ov["modes"]} == {m["id"] for m in res["modes"]}
    assert kit["floor"] == R.FLOOR and "matrix" in kit
    for m in kit["modes"]:
        if m["benchmarked"]:
            assert {"id", "fm", "name", "n", "best_j", "reliable", "rows"} <= set(m)
            for r in m["rows"]:
                assert {
                    "key",
                    "tool",
                    "short",
                    "category",
                    "j",
                    "tpr",
                    "fpr",
                    "cost1k",
                    "estimated",
                    "recommendable",
                } <= set(r)


def test_site_regexes_over_cost_note_still_work(built):
    """Until the site reads the explicit fields, its two regexes over cost_note must agree with them."""
    res, _, _ = built
    for m in res["modes"]:
        for r in m["rows"]:
            sub = re.search(
                r"run on the first (\d+) \+ (\d+) samples only", r["cost_note"] or ""
            )
            if r["subset_n"]:
                assert sub and (int(sub[1]), int(sub[2])) == (
                    r["subset_n"]["pos"],
                    r["subset_n"]["neg"],
                )
            else:
                assert not sub
            assert ("estimated" in (r["cost_note"] or "")) == r["cost_estimated"], (
                m["id"],
                r["key"],
            )


def test_stamp_names_every_input_with_its_checksum(built):
    import hashlib

    res, _, _ = built
    assert res["version"] == R.RESULTS_VERSION and res["cite_as"].endswith(
        R.RESULTS_VERSION
    )
    assert re.fullmatch(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z", res["generated_at"])
    paths = [i["path"] for i in res["inputs"]]
    assert paths == sorted(paths) and len(set(paths)) == len(paths)
    assert any(p.endswith("published/scores.json") for p in paths)
    assert (
        any(p.endswith(".csv") for p in paths)
        and "bench/kitbuilder/recipes.json" in paths
    )
    for i in res["inputs"]:
        assert (
            hashlib.sha256((REPO / i["path"]).read_bytes()).hexdigest() == i["sha256"]
        )


# ------------------------------------------------------------------------------------------- rules about "best"
def test_expected_rows_and_no_dropped_mode(built):
    res, _, _ = built
    assert not res["partial"] and len(res["modes"]) == len(R.EXPECTED_ROWS)
    for m in res["modes"]:
        reviewers = [r for r in m["rows"] if r["kind"] != R.KIND_SHORTCUT]
        assert (
            len(reviewers) >= R.EXPECTED_ROWS[m["id"]]
        )  # optional rows (a second bandit profile) come on top
        assert len({r["key"] for r in m["rows"]}) == len(m["rows"])


def test_baseline_rules_shortcuts_and_out_of_scope_rows_are_never_best(built):
    res, _, _ = built
    for m in res["modes"]:
        by = {r["key"]: r for r in m["rows"]}
        for r in m["rows"]:
            if r["kind"] in R.NEVER_BEST or (m["id"], r["key"]) in R.OUTSIDE_SCOPE:
                assert not r["ranked"] and r["unranked_reason"], (m["id"], r["key"])
                assert "rank" not in r and not r.get("in_top_group")
        ranked = sorted((r for r in m["rows"] if r["ranked"]), key=lambda r: r["rank"])
        assert [r["rank"] for r in ranked] == list(range(1, len(ranked) + 1))
        assert all(a["j"] >= b["j"] for a, b in zip(ranked, ranked[1:]))
        assert m["best_reviewer"]["key"] == ranked[0]["key"] == m["top_group"][0]
        assert all(by[k]["ranked"] for k in m["top_group"])
        t = m["best_catalog_tool"]
        if t:
            assert (
                by[t["key"]]["kind"] == R.KIND_TOOL
                and by[t["key"]]["check"] in R.CATALOG_TOOL_CHECKS
            )
            assert by[t["key"]]["ranked"]
        # a framework that ran our rubric, and a product that is not in the catalog, are labelled as such
        for r in m["rows"]:
            if r["key"] == "giskard":
                assert (
                    r["catalog"] == R.NOT_IN_CATALOG
                    and r["check"] == R.OUR_RUBRIC
                    and "kg_id" not in r
                )
            if r["key"] == "promptfoo":
                assert r["check"] == R.OUR_RUBRIC and r["kg_id"] == "promptfoo"
            if r["key"] in ("ruff_npy", "ruff_up"):
                assert r["kg_id"] == "ruff"


def test_a_winner_is_named_only_when_the_paired_interval_excludes_zero(built):
    res, _, src = built
    for m in res["modes"]:
        ranked = sorted((r for r in m["rows"] if r["ranked"]), key=lambda r: r["rank"])
        tied = [
            r["key"]
            for r in ranked[1:]
            if r["vs_best"] is not None and not r["vs_best"]["separable"]
        ]
        assert m["top_group"] == [ranked[0]["key"]] + tied
        assert (m["winner"] is None) == (len(m["top_group"]) > 1)
        for r in ranked[1:]:
            d = r["vs_best"]
            if d is not None:
                assert d["separable"] == (d["lo"] > 0 or d["hi"] < 0)
                assert (
                    d["n"] <= r["n_pos_readable"] + r["n_neg_readable"]
                )  # only samples both rows answered
        if m["below_floor"]:
            assert (
                "No best reviewer is named" in m["ranking"]
                and ranked[0]["short"] not in m["ranking"]
            )


def test_counts_in_the_findings_come_from_the_mode_records(built):
    res, _, _ = built
    modes, ov = res["modes"], res["overview"]
    con = [m for m in modes if m["provenance"]["positives"] == "constructed"]
    agent = [m for m in modes if m["provenance"]["agent_output"]]
    text = " ".join(lead + rest for lead, rest in ov["findings"])
    assert f"{len(con)} of the {len(modes)} sets have constructed positives" in text
    assert f"On the {len(agent)} sets of real agent output" in text
    single = sum(1 for m in modes if m["winner"])
    assert (
        f"A single best reviewer can be named in {single} of {len(modes)} modes."
        in text
    )
    wrap = ov["wrapper_comparisons"]
    worse = sum(c["verdict"] == "worse" for c in wrap)
    same = sum(c["verdict"] == "indistinguishable" for c in wrap)
    assert (
        f"{len(wrap)} comparisons on identical samples: {worse} worse, {same} indistinguishable"
        in text
    )
    assert (
        "4 of 4" not in text.replace("in 4 of 4 comparisons", "")
        and "8 of 9" not in text
    )
    assert "upper bound" not in json.dumps(res)
    for c in ov["counts"], ov["union_false_alarm"]:
        assert c
    assert ov["counts"]["constructed"] == len(con) and ov["counts"][
        "agent_output"
    ] == len(agent)
    assert (
        ov["union_false_alarm"]["status"] == "estimate under independence, not measured"
    )
    # modes are grouped by provenance and ordered by name inside a group, never by score
    order = [(m["group"], m["name"]) for m in ov["modes"]]
    gids = [g for g, _, _ in R.PROVENANCE_GROUPS]
    assert order == sorted(order, key=lambda x: (gids.index(x[0]), x[1]))


def test_every_tool_row_has_a_run_card_and_use_case_numbers(built):
    res, _, _ = built
    for m in res["modes"]:
        for r in m["rows"]:
            assert r["fa_per_100"] == pytest.approx(100 * r["fa"], abs=1e-4)
            assert set(r["ppv"]) == {f"{p:g}" for p in R.PREVALENCES}
            p5 = report_stats.precision_at(r["catch"], r["fa"], 0.05)
            assert r["ppv"]["0.05"] == (
                None if p5 is None else pytest.approx(p5, abs=1e-5)
            )
            if r["kind"] in (R.KIND_TOOL, R.KIND_UNCATALOGUED):
                card = r["run_card"]
                assert (
                    card["runs"] == r["n_pos"] + r["n_neg"]
                    and card["failed_runs"] == r["unreadable"]
                )
                assert card.get("version"), (m["id"], r["key"])
                if r.get("judge"):
                    assert card.get("judge_model") and card.get("deviations")
    assert {t["id"] for t in res["tiers"]} == {"well", "partly", "not-yet"}
    assert all("on our set" in t["label"] for t in res["tiers"])


# ------------------------------------------------------------------------------------------- costs
def test_costs_are_consistent_and_totals_are_real_spend(built):
    res, _, _ = built
    for m in res["modes"]:
        for r in m["rows"]:
            assert r["cost_basis"] in ("api", "list", "gpu", "mixed", "free")
            assert r["cost"] == pytest.approx(r["cost1k"] * m["n"] / 1000, abs=2e-6)
            if r["cost_basis"] == "free":
                assert r["cost"] == 0 and r["spend"] == 0
            if r["subset_n"] and r["cost_basis"] != "free":
                assert (
                    r["spend"] < r["cost"] and r["cost_estimated"]
                )  # the spend of a subset run is not scaled up
        assert m["spend"] == pytest.approx(sum(r["spend"] for r in m["rows"]), abs=1e-5)


def score_row(**over) -> dict:
    row = {
        "n_pos": 10,
        "n_neg": 10,
        "cost": 2.0,
        "cost_basis": "api",
        "cost_calls": 20,
        "cost_api": 2.0,
        "cost_list": 1.0,
    }
    row.update(over)
    return row


def test_row_cost_is_the_only_source_of_a_cost():
    c = build_report.row_cost(
        "m", "plain_llm_x", "baseline_model", score_row(), 20, 20, "hyperbolic"
    )
    assert (c["cost"], c["cost1k"], c["spend"], c["cost_estimated"]) == (
        2.0,
        100.0,
        2.0,
        False,
    )
    assert c["cost_other_basis"] == {"basis": "list", "cost1k": 50.0}
    free = build_report.row_cost(
        "m",
        "pyright",
        "deterministic",
        {"cost_basis": "free", "cost": 0.0},
        20,
        20,
        None,
    )
    assert free["cost"] == 0 and free["cost_basis"] == "free"
    # a subset run: the per-1,000 cost is measured on the subset, `cost` is scaled to the mode, `spend` is not
    sub = build_report.row_cost(
        "m", "kg_x", "llm_based", score_row(subset_per_label=10), 20, 200, "hyperbolic"
    )
    assert (
        sub["cost1k"] == 100.0
        and sub["cost"] == pytest.approx(20.0)
        and sub["spend"] == 2.0
    )
    assert (
        sub["cost_estimated"]
        and "run on the first 10 + 10 samples only" in sub["cost_note"]
    )
    # a relayed tool whose ledger holds calls for part of the run only: cost per review from the logged calls
    part = build_report.row_cost(
        "m",
        "pr_agent",
        "llm_based",
        score_row(cost_partial=True, cost_calls=10),
        20,
        20,
        "hyperbolic",
    )
    assert (
        part["spend_logged"] == 2.0
        and part["cost1k"] == pytest.approx(200.0)
        and part["cost_estimated"]
    )
    assert part["cost_other_basis"]["cost1k"] == pytest.approx(100.0)
    # fewer calls than reviews because runs failed: nothing is missing from the ledger, nothing is scaled
    failed = score_row(
        cost_partial=True, cost_calls=10, unreadable_causes={"tool_error": 10}
    )
    whole = build_report.row_cost(
        "m", "pr_agent", "llm_based", failed, 20, 20, "hyperbolic"
    )
    assert (
        whole["spend"] == 2.0
        and whole["cost1k"] == 100.0
        and not whole["cost_estimated"]
    )
    gpu = build_report.row_cost(
        "m",
        "plain_llm_gptoss",
        "baseline_model",
        score_row(
            cost_basis="gpu",
            cost_gpu_seconds=360,
            cost_estimated=True,
            cost_api=None,
            cost_list=None,
        ),
        20,
        20,
        "self_hosted_gpu",
    )
    assert (
        gpu["cost_basis"] == "gpu"
        and gpu["cost_estimated"]
        and "360 seconds" in gpu["cost_note"]
    )
    with pytest.raises(
        build_report.MissingInput
    ):  # a paid row without a cost stops the build
        build_report.row_cost(
            "m",
            "plain_llm_x",
            "baseline_model",
            score_row(cost=None, cost_basis="unpriced"),
            20,
            20,
            "x",
        )


def test_no_cost_is_typed_into_the_report_code():
    """B4: no dollar literal in the modules that build rows (prose about the dataset aside)."""
    code = (BENCH / "build_report.py").read_text() + (
        BENCH / "report_findings.py"
    ).read_text()
    assert not re.search(r"\b\d+\.\d{2},\s*(#|\")", code)
    assert "PR_AGENT_COST" not in code and "sec_heldout" not in code


# ------------------------------------------------------------------------------------------- statistics helpers
def test_top_group_keeps_rows_whose_difference_includes_zero():
    table = {
        ("a", "b"): {"separable": False},
        ("a", "c"): {"separable": True},
        ("a", "d"): None,
    }
    group, comps = report_stats.top_group(
        ["a", "b", "c", "d"], lambda x, y: table[(x, y)]
    )
    assert group == ["a", "b"] and set(comps) == {"b", "c", "d"}
    assert report_stats.top_group([], lambda x, y: None) == ([], {})


def test_precision_any_flag_and_tiers():
    assert report_stats.precision_at(1.0, 0.0, 0.05) == 1.0
    assert report_stats.precision_at(0.0, 0.0, 0.05) is None
    assert report_stats.precision_at(0.9, 0.1, 0.05) == pytest.approx(
        0.045 / (0.045 + 0.095)
    )
    assert (
        report_stats.any_flag_rate([0.5, 0.5]) == 0.75
        and report_stats.any_flag_rate([]) == 0
    )
    assert report_stats.tier_of(0.9, R.TIERS)["id"] == "well"
    assert report_stats.tier_of(R.FLOOR, R.TIERS)["id"] == "partly"
    assert report_stats.tier_of(0.1, R.TIERS)["id"] == "not-yet"


def test_and_list():
    assert report_findings.and_list([]) == "" and report_findings.and_list(["a"]) == "a"
    assert report_findings.and_list(["a", "b", "c"]) == "a, b and c"


# ------------------------------------------------------------------------------------------- guards
def test_tracked_results_match_a_rebuild(built):
    """The published file is what the tracked inputs give (rebuild with `python bench/build_report.py`)."""
    res, _, _ = built
    tracked = json.loads(TRACKED.read_text())
    diff = build_report.first_difference(
        build_report.strip_volatile(res), build_report.strip_volatile(tracked)
    )
    assert (
        diff is None
    ), f"site/public/bench/results.json is out of date; first difference at {diff}"


def test_a_missing_input_stops_the_build_and_writes_nothing(tmp_path):
    bench = shadow(tmp_path)
    shutil.rmtree(bench / "fabrication" / "published")
    out = tmp_path / "out"
    p = subprocess.run(
        [
            sys.executable,
            str(BENCH / "build_report.py"),
            "--bench-dir",
            str(bench),
            "--out-dir",
            str(out),
        ],
        capture_output=True,
        text=True,
    )
    assert (
        p.returncode == 2 and "missing input" in p.stderr and "fabrication" in p.stderr
    )
    assert not out.exists()


def test_a_missing_row_or_cost_stops_the_build(tmp_path):
    bench = shadow(tmp_path)
    f = bench / "scope_creep" / "published" / "scores.json"
    scores = json.loads(f.read_text())
    del scores["plain_llm_mimo"]
    f.write_text(json.dumps(scores))
    with pytest.raises(build_report.MissingInput, match="plain_llm_mimo"):
        build_report.build_mode(
            build_report.report_modes.scope_creep, build_report.Published(bench)
        )


def test_extras_built_from_an_older_verdict_table_stop_the_build(tmp_path):
    """extras.json sentences are computed from the verdict table; a stale one must not be published with new rows."""
    bench = shadow(tmp_path)
    f = bench / "logic_error" / "published" / "extras.json"
    extras = json.loads(f.read_text())
    assert extras["built_from"]
    extras["built_from"] = {
        path: "0" * 64 for path in extras["built_from"]
    }  # as if the table had changed since
    f.write_text(json.dumps(extras))
    with pytest.raises(build_report.MissingInput, match="extras.json is out of date"):
        build_report.build_mode(
            build_report.report_modes.logic_error, build_report.Published(bench)
        )


def test_results_diff_runs_on_two_versions():
    import results_diff

    old = json.loads(
        (BENCH / "report" / "versions" / "results-v1.0.0.json").read_text()
    )
    new = json.loads(TRACKED.read_text())
    lines = results_diff.diff(old, new, md=True)
    text = "\n".join(lines)
    assert (
        "Findings before (v1.0.0" in text
        and f"Findings after (v{new['version']}" in text
    )
    assert "| plain_llm_mimo |" in text and " 0 dropped." in text


def test_allow_missing_marks_the_output_partial(tmp_path):
    bench = shadow(tmp_path)
    shutil.rmtree(bench / "supply_chain" / "published")
    results, _, _ = build_report.build(bench, allow_missing=True)
    assert results["partial"] and list(results["missing_modes"]) == ["supply_chain"]
    assert len(results["modes"]) == len(R.EXPECTED_ROWS) - 1
    text = " ".join(lead for lead, _ in results["overview"]["findings"])
    assert (
        f"of {len(results['modes'])} modes" in text
    )  # counts follow what was built, and the file says it is partial
    with pytest.raises(build_report.MissingInput):
        build_report.build(bench)


# ------------------------------------------------------------------------------------------- stand-alone page
def test_page_embeds_the_results_and_its_script_parses(built, tmp_path):
    res, _, _ = built
    html = report_page.render(res)
    blob = html.split("const RES = ", 1)[1].split(";\nconst DATA", 1)[0]
    assert "</" not in blob
    data = json.loads(blob.replace("<\\/", "</"))
    assert [m["id"] for m in data["modes"]] == [
        m["id"] for m in res["modes"]
    ] and "inputs" not in data
    assert (
        "OV_DEFAULT_OFF" not in html and "Average quality vs average cost" not in html
    )
    node = shutil.which("node")
    if node:
        js = tmp_path / "page.js"
        js.write_text(html.split("<script>", 1)[1].rsplit("</script>", 1)[0])
        assert (
            subprocess.run([node, "--check", str(js)], capture_output=True).returncode
            == 0
        )
