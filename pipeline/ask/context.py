"""Turn a list of retrieval hits into a Kimi-ready context block.

Loads each node's YAML from ``data/`` on demand (cached per-process) and
extracts a compact per-node summary — id, type, name, and the most
descriptive text field for that node kind. Built separately from
``server.py`` so tests can exercise the builder without spinning up
FastAPI.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Iterable

import yaml

from pipeline.config import REPO_ROOT

log = logging.getLogger(__name__)

DATA_DIR = REPO_ROOT / "data"

# Map node_type -> (subdir on disk, URL prefix on the static site).
# Recipe + Incident dirs are declared here even before their site routes
# ship so that ``/ask`` retrieval works the moment their data lands — the
# citation URLs will 404 until the pages exist, which is a pre-existing
# site-wide convention for forthcoming node types.
NODE_TYPES: dict[str, tuple[str, str]] = {
    "tool": ("tools", "/tools"),
    "failure_mode": ("failure_modes", "/failure-modes"),
    "taxonomy": ("taxonomies", "/taxonomies"),
    "paper": ("papers", "/papers"),
    "incident": ("incidents", "/incidents"),
    "recipe": ("recipes", "/recipes"),
}

# Max chars of the "descriptive" field we ship per node. Kimi's context
# window is huge, but we still want to keep the prompt focused — 12 nodes
# × ~800 chars is roughly 10k chars of context, well under any model limit.
SNIPPET_CHARS = 800


@dataclass(frozen=True)
class NodeContext:
    """One retrieval hit, hydrated from disk, ready to render."""

    id: str
    type: str
    name: str
    snippet: str
    similarity: float

    @property
    def url(self) -> str:
        prefix = NODE_TYPES.get(self.type, ("", ""))[1]
        return f"{prefix}/{self.id}" if prefix else ""


def _detect_type_and_path(node_id: str) -> tuple[str, Path] | None:
    """Resolve a bare node id to (type, on-disk path) by scanning subdirs.

    Node ids are globally unique across directories — same id never
    appears in two places — so the first hit wins.
    """
    for node_type, (subdir, _) in NODE_TYPES.items():
        for ext in (".yml", ".yaml"):
            candidate = DATA_DIR / subdir / f"{node_id}{ext}"
            if candidate.exists():
                return node_type, candidate
    return None


@lru_cache(maxsize=512)
def _load_node_yaml(node_id: str) -> tuple[str, dict] | None:
    """Load node YAML by id. Returns (node_type, data) or None if not found."""
    resolved = _detect_type_and_path(node_id)
    if resolved is None:
        return None
    node_type, path = resolved
    try:
        doc = yaml.safe_load(path.read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError) as exc:
        log.warning("failed to load %s: %s", path, exc)
        return None
    if not isinstance(doc, dict):
        return None
    return node_type, doc


def _extract_description(node_type: str, data: dict) -> str:
    """Pull the most informative free-text field for this node type.

    The field name varies by node kind. Papers use ``tldr``/``notes``;
    taxonomies use ``scope``; everyone else uses ``description`` /
    ``tagline``. Fall back to an empty string rather than crashing —
    citations still work without a snippet.
    """
    if node_type == "paper":
        # Papers keep the punchiest line in `tldr`; `notes` is editorial.
        text = data.get("tldr") or data.get("notes") or data.get("title") or ""
    elif node_type == "incident":
        # Incidents tell a story — `description` is the narrative, `tagline`
        # the headline. Prefer tagline first (compact, already-edited).
        text = data.get("tagline") or data.get("description") or ""
    elif node_type == "taxonomy":
        # `scope` is the human-oriented description; fall back to categories summary.
        text = data.get("scope") or ""
        if not text and isinstance(data.get("categories"), list):
            labels = [
                f"{c.get('external_id', '')}: {c.get('label', '')}"
                for c in data["categories"]
                if isinstance(c, dict)
            ]
            text = "; ".join(labels[:10])
    else:
        # tool / failure_mode / (future) recipe / incident share the same shape.
        text = data.get("description") or data.get("tagline") or ""
    return str(text).strip()


def _extract_name(node_type: str, data: dict) -> str:
    if node_type in ("paper", "incident"):
        return str(data.get("title") or data.get("name") or data.get("id") or "")
    return str(data.get("name") or data.get("id") or "")


def hydrate(hits: Iterable[tuple[str, float]]) -> list[NodeContext]:
    """Resolve ``(node_id, similarity)`` pairs to :class:`NodeContext` records.

    Hits whose id doesn't resolve to a known YAML file are dropped with a
    warning — the caller gets back fewer records than it asked for but
    never a broken citation.
    """
    out: list[NodeContext] = []
    for node_id, sim in hits:
        loaded = _load_node_yaml(node_id)
        if loaded is None:
            log.warning("ask: retrieval hit %r did not resolve to a known node", node_id)
            continue
        node_type, data = loaded
        snippet = _extract_description(node_type, data)
        if len(snippet) > SNIPPET_CHARS:
            snippet = snippet[: SNIPPET_CHARS - 1].rstrip() + "…"
        out.append(
            NodeContext(
                id=str(data.get("id") or node_id),
                type=node_type,
                name=_extract_name(node_type, data),
                snippet=snippet,
                similarity=float(sim),
            )
        )
    return out


def render_context_block(nodes: list[NodeContext]) -> str:
    """Format hydrated nodes as a single string ready to splice into the prompt."""
    if not nodes:
        return "(no context — retrieval returned zero hits)"
    lines: list[str] = []
    for n in nodes:
        header = f"[{n.id}] ({n.type}) {n.name}".rstrip()
        body = n.snippet or "(no description)"
        lines.append(f"{header}\n{body}")
    return "\n\n---\n\n".join(lines)


PROMPT_TEMPLATE = """\
You are the SAICA-KG assistant. Answer the user's question using ONLY the
provided KG node context below. Every factual claim must cite a node id
in brackets, e.g., "PydanticAI validates structured outputs [pydantic-ai]".
If the KG doesn't support an answer, say "The KG doesn't have this information."
Do not fabricate node ids.

Context:
{context_blocks}

Question: {question}
"""


def build_prompt(question: str, nodes: list[NodeContext]) -> str:
    return PROMPT_TEMPLATE.format(
        context_blocks=render_context_block(nodes),
        question=question.strip(),
    )


__all__ = [
    "NODE_TYPES",
    "NodeContext",
    "build_prompt",
    "hydrate",
    "render_context_block",
    "PROMPT_TEMPLATE",
]
