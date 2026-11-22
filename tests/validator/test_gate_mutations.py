"""Mutation test for the KG gate (``validator/cli.py``).

Each case below seeds one defect and states the error line the gate must
print. Every case runs twice:

* on the small fixture graph from ``kg_fixture.make_kg`` (always clean before
  the defect, so "exit 1 and the message" is exact), and
* on a scratch copy of the live ``data/`` directory (the message must appear
  after the defect and must not be there before it).

The list started as the 18 seeded defect classes of the 2026-11-21 review
(PV-06): 14 passed with exit 0 and 2 crashed. A new invariant gets a case
here, so the list of caught defects is itself tested.
"""

from __future__ import annotations

import json
import shutil
from pathlib import Path
from typing import Any, Callable

import pytest
import yaml

from kg_fixture import edit_yaml, make_kg, read_yaml, run_gate, write_yaml

REPO = Path(__file__).resolve().parents[2]
LIVE_DATA = REPO / "data"


# ---------------------------------------------------------------------------
# Picking targets that exist in whichever tree is under test
# ---------------------------------------------------------------------------


def _files(data: Path, kind: str) -> list[Path]:
    return sorted((data / kind).glob("*.yml"))


def _first(
    data: Path, kind: str, wanted: Callable[[dict[str, Any]], bool] = lambda n: True
) -> Path:
    for path in _files(data, kind):
        try:
            node = read_yaml(path)
        except yaml.YAMLError:
            continue
        if isinstance(node, dict) and wanted(node):
            return path
    pytest.skip(f"no suitable file under {kind}/ in this tree")


def _tool(data: Path) -> Path:
    preferred = data / "tools" / "ruff.yml"
    return preferred if preferred.exists() else _first(data, "tools")


def _drop_from_manifest(data: Path, kind: str, node_id: str) -> None:
    path = data / "MANIFEST.json"
    if not path.exists():
        return
    doc = json.loads(path.read_text())
    entry = doc.get("ids", {}).get(kind)
    if isinstance(entry, dict):
        entry.pop(node_id, None)
    elif isinstance(entry, list) and node_id in entry:
        entry.remove(node_id)
    path.write_text(json.dumps(doc, indent=2) + "\n")


# ---------------------------------------------------------------------------
# The seeded defects. Each returns the fragments that one error line of the
# gate must contain (a string, or several strings for the same line).
# ---------------------------------------------------------------------------

Expected = str | tuple[str, ...]


def _has_line(output: str, expected: Expected) -> bool:
    fragments = (expected,) if isinstance(expected, str) else expected
    return any(all(f in line for f in fragments) for line in output.splitlines())


def two_files_same_id(data: Path) -> Expected:
    src = _tool(data)
    shutil.copy(src, src.with_name(f"{src.stem}-copy.yml"))
    return f"id '{src.stem}' is used by two files"


def id_differs_from_file_name(data: Path) -> Expected:
    src = _tool(data)
    doc = read_yaml(src)
    doc["id"] = "totally-different"
    doc["repository_url"] = "https://github.com/example/totally-different"
    write_yaml(data / "tools" / "zzz.yml", doc)
    return "id 'totally-different' does not equal the file name 'zzz'"


def id_changed_inside_file(data: Path) -> Expected:
    src = _tool(data)
    edit_yaml(src, lambda d: d.update(id=f"{d['id']}-renamed"))
    return f"does not equal the file name '{src.stem}'"


def paper_entered_twice(data: Path) -> Expected:
    src = _first(data, "papers", lambda n: bool(n.get("arxiv_id")))
    doc = read_yaml(src)
    doc["id"] = "zzz-duplicate-paper"
    write_yaml(data / "papers" / "zzz-duplicate-paper.yml", doc)
    return "zzz-duplicate-paper has the same arxiv_id as"


def paper_same_doi(data: Path) -> Expected:
    src = _first(data, "papers", lambda n: bool(n.get("doi")))
    doi = read_yaml(src)["doi"]
    write_yaml(
        data / "papers" / "zzz-same-doi.yml",
        {
            "id": "zzz-same-doi",
            "authors": ["Someone Else"],
            "year": 2025,
            "title": "A completely different title zzz",
            "doi": f"https://doi.org/{str(doi).upper()}",
        },
    )
    return "zzz-same-doi has the same doi as"


def paper_same_title(data: Path) -> Expected:
    src = _first(data, "papers")
    title = read_yaml(src)["title"]
    write_yaml(
        data / "papers" / "zzz-same-title.yml",
        {
            "id": "zzz-same-title",
            "authors": ["Someone Else"],
            "year": 2025,
            "title": f"  {str(title).upper()} ",
        },
    )
    return "zzz-same-title has the same title as"


def tool_entered_twice(data: Path) -> Expected:
    src = _first(data, "tools", lambda n: bool(n.get("repository_url")))
    doc = read_yaml(src)
    doc["id"] = "zzz-same-repo"
    doc["repository_url"] = str(doc["repository_url"]).rstrip("/") + ".git"
    write_yaml(data / "tools" / "zzz-same-repo.yml", doc)
    return "zzz-same-repo has the same repository_url as"


def evaluated_on_missing(data: Path) -> Expected:
    edit_yaml(_tool(data), lambda d: d.update(evaluated_on=["no-such-paper"]))
    return "evaluated_on 'no-such-paper' is neither a paper id"


def feeds_into_missing(data: Path) -> Expected:
    edit_yaml(_tool(data), lambda d: d.update(feeds_into=["no-such-tool"]))
    return "feeds_into missing tool 'no-such-tool'"


def related_modes_missing(data: Path) -> Expected:
    src = _first(data, "failure_modes")
    edit_yaml(src, lambda d: d.update(related_modes=["not_a_mode"]))
    return "related_modes names unknown FailureMode 'not_a_mode'"


def related_modes_one_way(data: Path) -> Expected:
    path = data / "failure_modes" / "scope_creep.yml"
    other = "test_manipulation"
    if not path.exists() or not (data / "failure_modes" / f"{other}.yml").exists():
        pytest.skip("failure-mode files not in this tree")
    if "scope_creep" in (
        read_yaml(data / "failure_modes" / f"{other}.yml").get("related_modes") or []
    ):
        other = "dependency_blindness"
    edit_yaml(
        path, lambda d: d.update(related_modes=[*(d.get("related_modes") or []), other])
    )
    return f"scope_creep lists '{other}' in related_modes but {other} does not list scope_creep"


def canonical_definition_source_missing(data: Path) -> Expected:
    src = _first(data, "failure_modes")
    edit_yaml(src, lambda d: d.update(canonical_definition_source="no-such-paper"))
    return "canonical_definition_source is missing paper 'no-such-paper'"


def crosswalk_value_not_on_axis(data: Path) -> Expected:
    src = _first(data, "crosswalks", lambda n: n.get("saica_axis") == "failure_mode")

    def change(doc: dict[str, Any]) -> None:
        doc["mappings"][0]["saica_value"] = "not_a_failure_mode"

    edit_yaml(src, change)
    return "saica_value 'not_a_failure_mode' is not a value of the failure_mode axis"


def failure_mode_file_deleted(data: Path) -> Expected:
    target = data / "failure_modes" / "context_pollution.yml"
    if not target.exists():
        pytest.skip("context_pollution.yml not in this tree")
    target.unlink()
    _drop_from_manifest(data, "failure_modes", "context_pollution")
    return "context_pollution has no file in data/failure_modes/"


def _placeholder(field: str) -> Callable[[Path], Expected]:
    def mutate(data: Path) -> Expected:
        src = _tool(data)
        edit_yaml(src, lambda d: d.update({field: "REVIEW_REQUIRED"}))
        return (
            f"[tools] {src.name} :: line",
            "REVIEW_REQUIRED marker left in the file",
        )

    mutate.__name__ = f"review_required_in_{field}"
    return mutate


def review_required_comment(data: Path) -> Expected:
    src = _tool(data)
    src.write_text(src.read_text() + "\n# REVIEW REQUIRED: facets below 0.85\n")
    return (f"[tools] {src.name} :: line", "REVIEW_REQUIRED marker left in the file")


def todo_as_value(data: Path) -> Expected:
    src = _tool(data)
    edit_yaml(src, lambda d: d.update(license="TODO"))
    return f"{src.name} :: license — placeholder text 'TODO' is not a value"


def key_written_twice(data: Path) -> Expected:
    src = _tool(data)
    src.write_text(src.read_text() + "\naddresses_failure_modes:\n  - scope_creep\n")
    return (src.name, "key 'addresses_failure_modes' is written twice")


def yaml_syntax_error(data: Path) -> Expected:
    src = _tool(data)
    src.write_text(src.read_text() + "\nbroken: [unclosed\n")
    return f"{src.name} :: <file> — cannot be read as YAML"


def mode_listed_twice(data: Path) -> Expected:
    def change(doc: dict[str, Any]) -> None:
        doc["addresses_failure_modes"].append(doc["addresses_failure_modes"][0])

    src = _tool(data)
    edit_yaml(src, change)
    return (f"{src.name} :: addresses_failure_modes — '", "is listed twice")


def composes_with_itself(data: Path) -> Expected:
    src = _tool(data)
    edit_yaml(src, lambda d: d.update(composes_with=[d["id"]]))
    return f"{src.stem} composes_with names itself"


def repository_url_not_a_url(data: Path) -> Expected:
    src = _tool(data)
    edit_yaml(src, lambda d: d.update(repository_url="not a url"))
    return f"{src.name} :: repository_url — 'not a url' is not an http(s) URL"


def documentation_url_javascript(data: Path) -> Expected:
    src = _tool(data)
    edit_yaml(src, lambda d: d.update(documentation_url="javascript:alert(1)"))
    return (
        f"{src.name} :: documentation_url — 'javascript:alert(1)' is not an"
        " http(s) URL"
    )


def first_released_in_future(data: Path) -> Expected:
    src = _tool(data)
    edit_yaml(
        src,
        lambda d: d.update(first_released="2099-01-01", last_updated="2099-01-02"),
    )
    return f"{src.name} :: first_released — 2099-01-01 is in the future"


def last_updated_before_first_released(data: Path) -> Expected:
    src = _tool(data)

    def change(doc: dict[str, Any]) -> None:
        doc.pop("upstream_pushed_at", None)
        doc.pop("last_reviewed", None)
        doc.update(first_released="2024-05-01", last_updated="2023-01-01")

    edit_yaml(src, change)
    return (
        f"{src.name} :: last_updated — 2023-01-01 is before first_released"
        " 2024-05-01"
    )


def pushed_after_review(data: Path) -> Expected:
    src = _tool(data)
    edit_yaml(
        src,
        lambda d: d.update(
            first_released="2024-05-01",
            last_updated="2026-01-01",
            upstream_pushed_at="2026-06-01",
            last_reviewed="2026-01-01",
        ),
    )
    return (
        f"{src.name} :: last_reviewed — 2026-01-01 is before upstream_pushed_at"
        " 2026-06-01"
    )


def incident_source_not_a_url(data: Path) -> Expected:
    src = _first(data, "incidents")
    edit_yaml(src, lambda d: d.update(source_urls=["not-a-url"]))
    return f"{src.name} :: source_urls/0 — 'not-a-url' is not an http(s) URL"


def incident_date_in_future(data: Path) -> Expected:
    src = _first(data, "incidents")
    edit_yaml(src, lambda d: d.update(incident_date="2099-01-01"))
    return f"{src.name} :: incident_date — 2099-01-01 is in the future"


def recipe_stack_same_tool_twice(data: Path) -> Expected:
    def change(doc: dict[str, Any]) -> None:
        doc["stack"].append(doc["stack"][0])

    src = _first(data, "recipes")
    edit_yaml(src, change)
    return (f"{src.name} :: stack — '", "is listed twice")


def recipe_target_not_addressed(data: Path) -> Expected:
    recipe = _first(data, "recipes")
    doc = read_yaml(recipe)
    addressed: set[str] = set()
    for tool_id in doc["stack"]:
        tool = read_yaml(data / "tools" / f"{tool_id}.yml")
        addressed |= set(tool["addresses_failure_modes"])
    for mode in ("cascading_failure", "dependency_blindness", "test_manipulation"):
        if mode not in addressed and mode not in doc["targets_failure_modes"]:
            edit_yaml(recipe, lambda d: d["targets_failure_modes"].append(mode))
            return (
                f"[recipes] {recipe.stem} targets '{mode}' but no tool in its"
                " stack addresses that mode"
            )
    pytest.skip("the first recipe's stack addresses every probe mode")


def priorities_unknown_mode(data: Path) -> Expected:
    path = data / "failure_mode_priorities.yml"
    if not path.exists():
        pytest.skip("no priorities file")

    def change(doc: dict[str, Any]) -> None:
        doc["priorities"]["not_a_mode"] = {"likelihood": 0.1, "impact": 1}

    edit_yaml(path, change)
    return "priorities/not_a_mode — unknown FailureMode"


def priorities_mode_missing(data: Path) -> Expected:
    path = data / "failure_mode_priorities.yml"
    if not path.exists():
        pytest.skip("no priorities file")
    edit_yaml(path, lambda d: d["priorities"].pop("scope_creep"))
    return "no entry for 'scope_creep'"


def synonyms_unknown_paper(data: Path) -> Expected:
    path = data / "failure_mode_synonyms.yml"
    if not path.exists():
        pytest.skip("no synonyms file")

    def change(doc: dict[str, Any]) -> None:
        blocks = doc.get("failure_modes", doc)
        blocks["fabrication"]["anchor_papers"] = ["no-such-paper"]

    edit_yaml(path, change)
    return "fabrication/anchor_papers — missing paper 'no-such-paper'"


def synonyms_unknown_mode(data: Path) -> Expected:
    path = data / "failure_mode_synonyms.yml"
    if not path.exists():
        pytest.skip("no synonyms file")

    def change(doc: dict[str, Any]) -> None:
        blocks = doc.get("failure_modes", doc)
        blocks["not_a_mode"] = {"canonical": "x", "synonyms": ["y"]}

    edit_yaml(path, change)
    return "not_a_mode — unknown FailureMode"


def yaml_extension(data: Path) -> Expected:
    src = _tool(data)
    src.rename(src.with_suffix(".yaml"))
    return f"{src.stem}.yaml :: <file> — use the .yml extension"


def list_left_empty(data: Path) -> Expected:
    """Crashed with a TypeError before 2026-11-21."""
    src = _tool(data)
    edit_yaml(src, lambda d: d.update(cited_in=None))
    return f"{src.name} :: cited_in — is empty (null)"


def node_without_id(data: Path) -> Expected:
    """Crashed with a KeyError before 2026-11-21."""
    src = _first(data, "incidents")
    edit_yaml(src, lambda d: d.pop("id"))
    return f"{src.name} :: id — 'id' is a required property"


def string_where_integer_expected(data: Path) -> Expected:
    src = _tool(data)
    edit_yaml(src, lambda d: d.update(stars="12"))
    return f"{src.name} :: stars — Input should be a valid integer"


def et_al_as_author(data: Path) -> Expected:
    def clean(node: dict[str, Any]) -> bool:
        return not any("et al" in str(a).lower() for a in node.get("authors") or [])

    def change(doc: dict[str, Any]) -> None:
        doc["authors"] = [doc["authors"][0], "et al."]

    src = _first(data, "papers", clean)
    edit_yaml(src, change)
    return f"{src.name} :: authors/1 — 'et al.' is not an author"


def arxiv_version_without_arxiv_id(data: Path) -> Expected:
    src = _first(data, "papers", lambda n: not n.get("arxiv_id"))
    edit_yaml(src, lambda d: d.update(arxiv_version="v2"))
    return f"{src.name} :: arxiv_version — is set but the record has no arxiv_id"


def _unverified_taxonomy(data: Path) -> tuple[Path, str]:
    crosswalk = read_yaml(_first(data, "crosswalks"))
    tax = data / "taxonomies" / f"{crosswalk['taxonomy']}.yml"

    def change(doc: dict[str, Any]) -> None:
        doc.pop("verified_against_source", None)
        doc["notes"] = (
            "Category labels paraphrased for seed. Verify against the original"
            " post before v0.1 release."
        )

    edit_yaml(tax, change)
    return tax, crosswalk["id"]


def crosswalk_to_unverified_taxonomy(data: Path) -> Expected:
    tax, crosswalk_id = _unverified_taxonomy(data)
    return (
        f"[crosswalks] {crosswalk_id} maps to taxonomy '{tax.stem}', whose notes"
        " say its labels were never checked"
    )


def incident_on_unverified_taxonomy(data: Path) -> Expected:
    tax, _ = _unverified_taxonomy(data)
    doc = read_yaml(tax)
    if not doc.get("url"):
        pytest.skip("taxonomy has no url")
    incident = _first(data, "incidents")
    edit_yaml(incident, lambda d: d["source_urls"].append(doc["url"]))
    return f"[incidents] {incident.stem} rests on taxonomy '{tax.stem}'"


def unmapped_category_unknown(data: Path) -> Expected:
    src = _first(data, "crosswalks")

    def change(doc: dict[str, Any]) -> None:
        doc.setdefault("unmapped", []).append(
            {"category": "NO-SUCH-CATEGORY", "reason": "x"}
        )

    edit_yaml(src, change)
    return "unmapped category 'NO-SUCH-CATEGORY' is not a category of taxonomy"


def unmapped_and_mapped(data: Path) -> Expected:
    src = _first(data, "crosswalks")

    def change(doc: dict[str, Any]) -> None:
        ext = doc["mappings"][0]["external_id"]
        doc.setdefault("unmapped", []).append({"category": ext, "reason": "x"})

    edit_yaml(src, change)
    return (f"[crosswalks] {src.stem} lists", "as unmapped and also maps it")


def unmapped_list_incomplete(data: Path) -> Expected:
    """Dropping a listed parent leaves its children unaccounted for."""
    src = _first(data, "crosswalks", lambda n: bool(n.get("unmapped")))
    edit_yaml(src, lambda d: d["unmapped"].pop())
    return (
        f"[crosswalks] {src.stem}: category '",
        "is neither mapped nor listed under unmapped",
    )


def human_reviewed_without_reviewer(data: Path) -> Expected:
    src = _first(data, "crosswalks")

    def change(doc: dict[str, Any]) -> None:
        doc["review_state"] = "human_reviewed"
        doc.pop("reviewed_by", None)

    edit_yaml(src, change)
    return (
        f"{src.name} :: review_state — 'human_reviewed' needs the reviewers in"
        " reviewed_by"
    )


def node_deleted_without_tombstone(data: Path) -> Expected:
    if not (data / "MANIFEST.json").exists():
        pytest.skip("no manifest in this tree")
    manifest = json.loads((data / "MANIFEST.json").read_text())
    for path in _files(data, "incidents"):
        if path.stem in manifest.get("ids", {}).get("incidents", []):
            path.unlink()
            return f"incidents id '{path.stem}' is in MANIFEST.json but no longer"
    pytest.skip("no incident file is listed in the manifest")


def tombstoned_id_in_use(data: Path) -> Expected:
    src = _tool(data)
    path = data / "TOMBSTONES.yml"
    doc = read_yaml(path) if path.exists() else {"tombstones": []}
    doc["tombstones"].append(
        {
            "id": src.stem,
            "kind": "tool",
            "removed_on": "2026-11-21",
            "reason": "test",
        }
    )
    write_yaml(path, doc)
    return f"tool '{src.stem}' has a tombstone but data/tools/{src.stem}.yml exists"


MUTATIONS: list[Callable[[Path], Expected]] = [
    # --- the 18 classes of the 2026-11-21 review (PV-06) ---
    two_files_same_id,
    id_differs_from_file_name,
    paper_entered_twice,
    evaluated_on_missing,
    feeds_into_missing,
    related_modes_missing,
    canonical_definition_source_missing,
    crosswalk_value_not_on_axis,
    failure_mode_file_deleted,
    _placeholder("license"),
    _placeholder("description"),
    _placeholder("name"),
    key_written_twice,
    mode_listed_twice,
    composes_with_itself,
    repository_url_not_a_url,
    documentation_url_javascript,
    first_released_in_future,
    last_updated_before_first_released,
    incident_source_not_a_url,
    incident_date_in_future,
    recipe_stack_same_tool_twice,
    priorities_unknown_mode,
    synonyms_unknown_paper,
    yaml_extension,
    list_left_empty,
    node_without_id,
    id_changed_inside_file,
    # --- added with the invariants of the fix round ---
    paper_same_doi,
    paper_same_title,
    tool_entered_twice,
    related_modes_one_way,
    review_required_comment,
    todo_as_value,
    yaml_syntax_error,
    pushed_after_review,
    recipe_target_not_addressed,
    priorities_mode_missing,
    synonyms_unknown_mode,
    string_where_integer_expected,
    et_al_as_author,
    arxiv_version_without_arxiv_id,
    crosswalk_to_unverified_taxonomy,
    incident_on_unverified_taxonomy,
    unmapped_category_unknown,
    unmapped_and_mapped,
    unmapped_list_incomplete,
    human_reviewed_without_reviewer,
    node_deleted_without_tombstone,
    tombstoned_id_in_use,
]
IDS = [m.__name__ for m in MUTATIONS]


# ---------------------------------------------------------------------------
# Fixture graph: clean before, exit 1 and the exact message after
# ---------------------------------------------------------------------------


def test_fixture_graph_is_clean(kg: Path) -> None:
    code, output = run_gate(kg)
    assert code == 0, output
    assert "0 errors" in output


@pytest.mark.parametrize("mutate", MUTATIONS, ids=IDS)
def test_seeded_defect_fails_the_gate(
    mutate: Callable[[Path], Expected], kg: Path
) -> None:
    expected = mutate(kg)
    code, output = run_gate(kg)
    assert "Traceback" not in output
    assert code == 1, f"gate passed a seeded defect ({mutate.__name__}):\n{output}"
    assert _has_line(output, expected), f"expected {expected!r} in:\n{output}"


# ---------------------------------------------------------------------------
# Scratch copy of the live data/: the message appears only after the defect
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def live_baseline(tmp_path_factory: pytest.TempPathFactory) -> tuple[Path, str]:
    base = tmp_path_factory.mktemp("live") / "data"
    shutil.copytree(LIVE_DATA, base, ignore=shutil.ignore_patterns("saica_index"))
    _, output = run_gate(base)
    return base, output


@pytest.mark.parametrize("mutate", MUTATIONS, ids=IDS)
def test_seeded_defect_fails_on_copy_of_live_data(
    mutate: Callable[[Path], Expected],
    live_baseline: tuple[Path, str],
    tmp_path: Path,
) -> None:
    base, before = live_baseline
    data = tmp_path / "data"
    shutil.copytree(base, data)
    expected = mutate(data)
    assert not _has_line(before, expected), (
        f"the live data already shows {expected!r}; this case cannot tell"
        " whether the gate catches the seeded defect"
    )
    code, output = run_gate(data)
    assert "Traceback" not in output
    assert code == 1, f"gate passed a seeded defect ({mutate.__name__})"
    assert _has_line(output, expected), f"expected {expected!r} in:\n{output[-3000:]}"


def test_gate_never_writes_into_the_tree(kg: Path) -> None:
    before = {p: p.read_bytes() for p in kg.rglob("*") if p.is_file()}
    run_gate(kg)
    after = {p: p.read_bytes() for p in kg.rglob("*") if p.is_file()}
    assert before == after


def test_make_kg_is_importable_for_other_tests(tmp_path: Path) -> None:
    assert (make_kg(tmp_path) / "MANIFEST.json").exists()
