"""The root documents quote the published results and the catalog's size.
These tests fail when a quoted block or count is no longer what the source
says, so a stale README cannot pass CI.

Fix a red test with:
    .venv/bin/python bench/render_docs.py readme --insert README.md
    .venv/bin/python bench/render_docs.py llms --insert llms.txt
or by correcting the count in README.md.
"""

from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
RENDER = ROOT / "bench" / "render_docs.py"


@pytest.mark.parametrize(
    ("kind", "document"), [("readme", "README.md"), ("llms", "llms.txt")]
)
def test_results_block_is_what_the_renderer_writes(kind: str, document: str) -> None:
    done = subprocess.run(
        [sys.executable, str(RENDER), kind, "--check", str(ROOT / document)],
        cwd=ROOT,
        capture_output=True,
        text=True,
    )
    assert done.returncode == 0, (
        f"the results block in {document} is out of date; run\n"
        f"  .venv/bin/python bench/render_docs.py {kind} --insert {document}\n"
        f"{done.stdout}{done.stderr}"
    )


def test_readme_keeps_its_marker_pairs_in_order() -> None:
    text = (ROOT / "README.md").read_text(encoding="utf-8")
    marks = [
        "<!-- BENCH:LEAD:START -->",
        "<!-- BENCH:LEAD:END -->",
        "<!-- BENCH:TABLE:START -->",
        "<!-- BENCH:TABLE:END -->",
    ]
    places = [text.find(m) for m in marks]
    assert all(text.count(m) == 1 for m in marks), "each marker must be there once"
    assert places == sorted(places), "markers are out of order"


# README line -> folder under data/ whose *.yml files are counted
COUNTED = {
    r"\*\*(\d+)\*\* supervision tools": "tools",
    r"\*\*(\d+)\*\* failure modes": "failure_modes",
    r"\*\*(\d+)\*\* papers": "papers",
    r"\*\*(\d+)\*\* external taxonomies": "taxonomies",
    r"\*\*(\d+)\*\* crosswalks": "crosswalks",
    r"\*\*(\d+)\*\* incident records": "incidents",
    r"\*\*(\d+)\*\* named recipes": "recipes",
}


@pytest.mark.parametrize(("pattern", "folder"), sorted(COUNTED.items()))
def test_readme_counts_match_the_data_folder(pattern: str, folder: str) -> None:
    text = (ROOT / "README.md").read_text(encoding="utf-8")
    found = re.search(pattern, text)
    assert found, f"README.md no longer has a line matching {pattern!r}"
    on_disk = len(list((ROOT / "data" / folder).glob("*.yml")))
    assert (
        int(found.group(1)) == on_disk
    ), f"README.md says {found.group(1)} for data/{folder}/, the folder has {on_disk}"


RETIRED_CLAIMS = [
    r"best reviewer in 8 of 9",
    r"in 4 of 4 modes",
    r"\bunsolved\b",
    r"human-reviewed",
    r"never drift",
    r"runs in CI",
    r"full / MECE",
    r"localhost:4321",
]


@pytest.mark.parametrize(
    "document",
    ["README.md", "llms.txt", "CONTRIBUTING.md", "EDITORIAL_POLICY.md", "CITATION.cff"],
)
def test_retired_claims_do_not_come_back(document: str) -> None:
    text = (ROOT / document).read_text(encoding="utf-8")
    back = [c for c in RETIRED_CLAIMS if re.search(c, text, flags=re.IGNORECASE)]
    assert not back, f"{document} has wording the 2026-11-21 review retired: {back}"


def test_citation_names_the_published_results_version() -> None:
    import json

    results = json.loads(
        (ROOT / "site" / "public" / "bench" / "results.json").read_text(
            encoding="utf-8"
        )
    )
    cff = (ROOT / "CITATION.cff").read_text(encoding="utf-8")
    assert re.search(
        rf'^version: "{re.escape(results["version"])}"$', cff, flags=re.M
    ), f"CITATION.cff must say version: \"{results['version']}\""
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    cite = readme[readme.index("```bibtex") :]
    assert (
        results["cite_as"] in cite
    ), f"the BibTeX note in README.md must name {results['cite_as']!r}"
