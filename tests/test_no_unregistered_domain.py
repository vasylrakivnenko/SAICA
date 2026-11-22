"""K9 (review 2026-11-21): the domain ``saica-kg.dev`` is not registered and
the GitHub organisation ``saica-kg`` does not exist. Whoever registers
either name would receive every link and crawler contact that points
there. The project's site is ``saica.ai`` and the repository is
``github.com/vasylrakivnenko/SAICA``.

This test fails when one of the old names comes back in the files of the
schema / validator / ingestion track. Files of other tracks (the served
packages, the site, root documents) are checked by their own owners.
"""

from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

OLD_NAMES = re.compile(r"saica-kg\.dev|github\.com/saica-kg(?![\w-])")

# Directories and files this track owns.
OWNED = [
    "schema",
    "validator",
    "pipeline/models.py",
    "pipeline/db.py",
    "pipeline/README.md",
    "pipeline/cli",
    "pipeline/taxonomy_cluster",
    "pipeline/embeddings",
    "pipeline/maturity",
    "pipeline/sources",
    "pipeline/extract",
    "pipeline/nlp",
    "pipeline/rerank",
    "pipeline/graduate",
    "pipeline/discovery",
    "tests/validator",
    "research/README.md",
    "research/TAXONOMY_CLUSTER_STUDY.md",
    "research/PIPELINE_ARCHITECTURE.md",
    "research/ARCH_REVIEW_SYSTEM_DESIGN.md",
    "research/ARCH_REVIEW_RELIABILITY.md",
    "research/ARCH_REVIEW_GOVERNANCE.md",
]
TEXT_SUFFIXES = {".py", ".md", ".json", ".yml", ".yaml", ".sql", ".txt", ".toml"}


def _files() -> list[Path]:
    out: list[Path] = []
    for entry in OWNED:
        path = ROOT / entry
        if path.is_file():
            out.append(path)
        elif path.is_dir():
            out.extend(
                p
                for p in path.rglob("*")
                if p.is_file()
                and p.suffix in TEXT_SUFFIXES
                and "__pycache__" not in p.parts
            )
    return sorted(out)


def test_owned_paths_exist() -> None:
    missing = [e for e in OWNED if not (ROOT / e).exists()]
    assert not missing, f"update OWNED: {missing}"
    assert len(_files()) > 50


def test_no_unregistered_domain_or_organisation() -> None:
    hits: list[str] = []
    for path in _files():
        try:
            text = path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            continue
        for number, line in enumerate(text.splitlines(), start=1):
            if OLD_NAMES.search(line):
                hits.append(f"{path.relative_to(ROOT)}:{number}: {line.strip()[:120]}")
    assert not hits, (
        "unregistered domain or organisation name found; use saica.ai or"
        " github.com/vasylrakivnenko/SAICA:\n  " + "\n  ".join(hits)
    )


def test_schema_ids_use_the_project_domain() -> None:
    import json

    for path in sorted((ROOT / "schema").glob("*.schema.json")):
        schema_id = json.loads(path.read_text())["$id"]
        assert schema_id == f"https://saica.ai/schema/{path.name}", schema_id


def test_the_pattern_itself_catches_the_old_names() -> None:
    assert OLD_NAMES.search("see https://saica-kg.dev/assess")
    assert OLD_NAMES.search("(https://github.com/saica-kg/saica-kg)")
    assert not OLD_NAMES.search("https://github.com/saica-kg-fork/x")
    assert not OLD_NAMES.search("https://saica.ai/tools/")
