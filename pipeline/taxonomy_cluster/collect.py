"""Collect the flat 128-category corpus from the six ingested taxonomies.

Each row carries just enough metadata for downstream clustering + naming:

* ``source_tax_id``                    — e.g. ``owasp-agentic-top-10-2026``
* ``external_id``                      — e.g. ``ASI04``
* ``label``                            — short human name
* ``description``                      — long free-text (may be multi-line)
* ``citation_count_of_parent_taxonomy``— copied from the linked Paper YAML,
                                         or 0 if the taxonomy has no paper

Keeping this step isolated from the embedding + clustering pipeline makes
the corpus trivially snapshotable (``corpus.json``) and comparable across
runs — that stability matters because our downstream ARI/NMI numbers are
only meaningful if both sides of the comparison use the exact same 128
rows in the exact same order.
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Dict, List, Optional

import yaml

from pipeline.config import REPO_ROOT

DATA_DIR = REPO_ROOT / "data"
TAXONOMIES_DIR = DATA_DIR / "taxonomies"
PAPERS_DIR = DATA_DIR / "papers"
CROSSWALKS_DIR = DATA_DIR / "crosswalks"
FAILURE_MODES_DIR = DATA_DIR / "failure_modes"
TOOLS_DIR = DATA_DIR / "tools"


@dataclass
class CategoryRow:
    """One row of the 128-category corpus."""

    source_tax_id: str
    external_id: str
    label: str
    description: str
    citation_count_of_parent_taxonomy: int

    @property
    def key(self) -> str:
        """Globally-unique identifier used in every downstream artifact."""
        return f"{self.source_tax_id}::{self.external_id}"

    @property
    def text_for_embedding(self) -> str:
        """The exact string fed to the sentence-transformer encoder."""
        desc = (self.description or "").strip()
        label = (self.label or "").strip()
        if desc:
            return f"{label}. {desc}"
        return label


def _load_yaml(path: Path) -> Dict:
    with path.open("r", encoding="utf-8") as fh:
        return yaml.safe_load(fh) or {}


def _load_paper_citation_counts(papers_dir: Path = PAPERS_DIR) -> Dict[str, int]:
    """Map ``paper_id -> citation_count`` (0 for missing)."""
    out: Dict[str, int] = {}
    for p in sorted(papers_dir.glob("*.yml")):
        doc = _load_yaml(p)
        pid = doc.get("id")
        if not pid:
            continue
        out[pid] = int(doc.get("citation_count") or 0)
    return out


def collect_corpus(
    *,
    taxonomies_dir: Path = TAXONOMIES_DIR,
    papers_dir: Path = PAPERS_DIR,
) -> List[CategoryRow]:
    """Walk the taxonomy YAMLs and produce the flat corpus in a deterministic order.

    Order is (1) sorted taxonomy filename, then (2) category order as written
    in the YAML (which is the authors' intended order). This makes the 128-row
    indexing reproducible across runs.
    """
    citations = _load_paper_citation_counts(papers_dir)
    rows: List[CategoryRow] = []
    for path in sorted(taxonomies_dir.glob("*.yml")):
        doc = _load_yaml(path)
        tax_id = doc.get("id") or path.stem
        paper_id: Optional[str] = doc.get("paper_id")
        cc = citations.get(paper_id, 0) if paper_id else 0
        for cat in doc.get("categories") or []:
            ext = cat.get("external_id")
            if not ext:
                continue
            rows.append(
                CategoryRow(
                    source_tax_id=tax_id,
                    external_id=ext,
                    label=(cat.get("label") or "").strip(),
                    description=(cat.get("description") or "").strip(),
                    citation_count_of_parent_taxonomy=cc,
                )
            )
    return rows


# ---------------------------------------------------------------------------
# Crosswalk → (category, saica mode) lookup
# ---------------------------------------------------------------------------


def load_crosswalk_pairs(
    *,
    crosswalks_dir: Path = CROSSWALKS_DIR,
    failure_modes_dir: Path = FAILURE_MODES_DIR,
) -> List[Dict]:
    """Return a flat list of {taxonomy, external_id, saica_value, confidence} pairs.

    Merges the bulk crosswalk YAMLs with the inline ``crosswalks:`` blocks
    that some FailureMode YAMLs carry. Duplicates (same taxonomy+external_id
    appearing in both) are kept — a downstream consumer can dedup via set
    semantics if it needs to.
    """
    pairs: List[Dict] = []

    for path in sorted(crosswalks_dir.glob("*.yml")):
        doc = _load_yaml(path)
        tax = doc.get("taxonomy")
        if not tax:
            continue
        for m in doc.get("mappings") or []:
            ext = m.get("external_id")
            sv = m.get("saica_value")
            if not ext or not sv:
                continue
            pairs.append(
                {
                    "taxonomy": tax,
                    "external_id": ext,
                    "saica_value": sv,
                    "confidence": m.get("confidence") or "related",
                }
            )

    for path in sorted(failure_modes_dir.glob("*.yml")):
        doc = _load_yaml(path)
        saica_value = doc.get("id")
        if not saica_value:
            continue
        for cw in doc.get("crosswalks") or []:
            tax = cw.get("taxonomy")
            ext = cw.get("external_id")
            if not tax or not ext:
                continue
            pairs.append(
                {
                    "taxonomy": tax,
                    "external_id": ext,
                    "saica_value": saica_value,
                    "confidence": cw.get("confidence") or "related",
                }
            )

    return pairs


def crosswalk_map(pairs: List[Dict]) -> Dict[str, List[str]]:
    """Group the flat pair list by ``"{taxonomy}::{external_id}"`` key."""
    out: Dict[str, List[str]] = {}
    for p in pairs:
        key = f"{p['taxonomy']}::{p['external_id']}"
        out.setdefault(key, [])
        if p["saica_value"] not in out[key]:
            out[key].append(p["saica_value"])
    return out


# ---------------------------------------------------------------------------
# Tool → addresses_failure_modes lookup
# ---------------------------------------------------------------------------


def load_tool_failure_modes(tools_dir: Path = TOOLS_DIR) -> Dict[str, List[str]]:
    """Map ``tool_id -> list of failure-mode ids it addresses``."""
    out: Dict[str, List[str]] = {}
    for path in sorted(tools_dir.glob("*.yml")):
        doc = _load_yaml(path)
        tid = doc.get("id")
        if not tid:
            continue
        modes = [m for m in (doc.get("addresses_failure_modes") or []) if m]
        if modes:
            out[tid] = modes
    return out


# ---------------------------------------------------------------------------
# Serialization
# ---------------------------------------------------------------------------


def rows_to_jsonable(rows: List[CategoryRow]) -> List[Dict]:
    return [asdict(r) for r in rows]


def write_corpus(rows: List[CategoryRow], out_path: Path) -> Path:
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with out_path.open("w", encoding="utf-8") as fh:
        json.dump(rows_to_jsonable(rows), fh, indent=2, sort_keys=False)
    return out_path
