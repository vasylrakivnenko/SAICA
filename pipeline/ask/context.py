"""Turn a list of retrieval hits into a Kimi-ready context block.

Loads each node's YAML from ``data/`` on demand (cached per-process) and
extracts a compact per-node summary — id, type, name, and the most
descriptive text field for that node kind. For ``tool`` nodes we also
carry the declared facets (addresses_failure_modes, control_paradigm,
temporal_phase, autonomy_level) plus an *inferred* integration-surface
list so the prompt can hold the LLM to two important rules:

  1. Don't recommend a tool for a failure mode it doesn't declare coverage for.
  2. When the user wants pipeline/API integration, don't recommend an
     IDE plugin or hosted web product.

Built separately from ``server.py`` so tests can exercise the builder
without spinning up FastAPI.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path
from typing import Iterable

import yaml

from pipeline.config import REPO_ROOT

log = logging.getLogger(__name__)

DATA_DIR = REPO_ROOT / "data"

NODE_TYPES: dict[str, tuple[str, str]] = {
    "tool": ("tools", "/tools"),
    "failure_mode": ("failure_modes", "/failure-modes"),
    "taxonomy": ("taxonomies", "/taxonomies"),
    "paper": ("papers", "/papers"),
    "incident": ("incidents", "/incidents"),
    "recipe": ("recipes", "/recipes"),
}

SNIPPET_CHARS = 800

# Keywords in the user's question that signal "I need to wire this into my
# own pipeline" and should bias recommendations toward headless surfaces.
PIPELINE_INTENT_RE = re.compile(
    r"\b(pipelin|ci/?cd\b|ci\b|workflow|automat|autonomous|headless|backend|"
    r"integrat|embed\b|library|sdk|api\b|proxy|gateway|cron\b|webhook|"
    r"github\s*action|pre-commit|mcp\b)",
    re.IGNORECASE,
)

# -- integration-surface detector --------------------------------------------
# Applied to tool YAML (name + tagline + description + rationale). Deliberately
# precision-biased; over-tagging muddies the answer, under-tagging just means
# the prompt can't use that hint. Tools can match multiple surfaces.
_SURFACE_RULES: tuple[tuple[str, re.Pattern[str]], ...] = (
    (
        "ide_plugin",
        re.compile(
            r"\b(vs\s?code(?:\sextension)?|vscode|jetbrains|intellij|pycharm|"
            r"neovim\splugin|emacs\spackage|ide\s(?:plugin|extension)|editor\sextension)\b",
            re.IGNORECASE,
        ),
    ),
    (
        "desktop_app",
        re.compile(
            r"\b(desktop\sapp(?:lication)?|standalone\s(?:ide|editor)|ai[- ]first\sIDE|"
            r"forked?\svs\s?code|ai\s?code\seditor|rust-based\sIDE)\b",
            re.IGNORECASE,
        ),
    ),
    (
        "web_app",
        re.compile(
            r"\b(in[- ]browser|hosted\sworkspace|web\sworkspace|web\sIDE|"
            r"browser-based\sIDE|generative\sUI|web\sapp\sbuilder|cloud\sworkspace|"
            r"ai\sapp\splatform|hosted\splatform\sUI)\b",
            re.IGNORECASE,
        ),
    ),
    (
        "cli",
        re.compile(
            r"\b(CLI\b|command[- ]line|terminal\stool|\-\-help\b|"
            r"\bnpx\s|\bpipx\s|invok(?:e|ed)\sfrom\s(?:the\s)?shell)\b",
            re.IGNORECASE,
        ),
    ),
    (
        "library",
        re.compile(
            r"\b(python\s(?:library|package|sdk)|typescript\s(?:library|sdk)|"
            r"node\s(?:library|package|sdk)|\bsdk\b|pip\sinstall|npm\sinstall|"
            r"imported?\s(?:as|in)\scode|programmatic(?:\sAPI)?|framework\sfor\s"
            r"building|decorator-based)\b",
            re.IGNORECASE,
        ),
    ),
    (
        "http_service",
        re.compile(
            r"\b(self[- ]hosted\sservice|rest\sapi|http\sapi|http\sservice|"
            r"http\sendpoint|observability\splatform|telemetry\sbackend|"
            r"tracing\sbackend|dashboard(?:\sservice)?|hosted\sendpoint)\b",
            re.IGNORECASE,
        ),
    ),
    (
        "mcp_server",
        re.compile(
            r"\b(mcp\sserver|model\scontext\sprotocol|mcp\sendpoint|mcp\scell)\b",
            re.IGNORECASE,
        ),
    ),
    (
        "ci_app",
        re.compile(
            r"\b(github\sactions?|gitlab\sci|pre[- ]commit|ci\sgate|ci\sgating|"
            r"dependabot|renovate|bot\sthat\sopens\sPRs?|PR\sbot|pull-request\sbot)\b",
            re.IGNORECASE,
        ),
    ),
    (
        "proxy_gateway",
        re.compile(
            r"\b(llm\sgateway|llm\sproxy|model\sgateway|intercepts?\s(?:calls|traffic)|"
            r"drop[- ]in\sproxy|unified\sproxy|sits?\sbetween\s(?:the\s)?caller|"
            r"transparent\sproxy)\b",
            re.IGNORECASE,
        ),
    ),
)

# Additional per-id overrides — for the cases where the description is a poor
# signal but the tool is unambiguous. Only adds what regex can't derive; the
# bulk-annotation script persists these into each YAML so that live /ask
# calls read the declared field rather than re-inferring.
_SURFACE_OVERRIDES: dict[str, tuple[str, ...]] = {
    # IDE / desktop / hosted coding agents
    "cursor": ("desktop_app",),
    "windsurf": ("desktop_app",),
    "zed-agent": ("desktop_app",),
    "replit-agent": ("web_app",),
    "v0": ("web_app",),
    "devin": ("web_app",),
    "github-copilot": ("ide_plugin",),
    "continue-dev": ("ide_plugin", "library"),
    "sourcegraph-cody": ("ide_plugin",),
    "claude-code": ("cli", "ide_plugin"),
    "codex-cli": ("cli",),
    "gemini-cli": ("cli",),
    "aider": ("cli",),
    "swe-agent": ("cli", "library"),
    "openhands": ("cli", "library"),
    # Static analysis / supply chain / CI
    "semgrep": ("cli", "ci_app", "library"),
    "snyk": ("cli", "ci_app"),
    "socket": ("ci_app",),
    "dependabot": ("ci_app",),
    "renovate": ("ci_app",),
    "pr-agent": ("ci_app", "cli"),
    # Guardrails / structured output / proxies
    "litellm": ("library", "proxy_gateway"),
    "bifrost": ("proxy_gateway", "http_service"),
    "llm-guard": ("library",),
    "guardrails-ai": ("library",),
    "nemo-guardrails": ("library",),
    "instructor": ("library",),
    "pydantic-ai": ("library",),
    "langgraph": ("library",),
    "crewai": ("library",),
    "autogen": ("library",),
    "agno": ("library",),
    "smolagents": ("library",),
    "letta": ("library", "http_service"),
    "mastra": ("library",),
    "voltagent": ("library",),
    "rebuff": ("library",),
    "superagent": ("library", "http_service"),
    "outlines": ("library",),
    "guidance": ("library",),
    "tree-sitter": ("library",),
    # Eval / red-team / testing harnesses
    "promptfoo": ("cli", "library", "ci_app"),
    "deepeval": ("library", "cli"),
    "confident-ai-deepteam": ("library", "cli"),
    "judgeval": ("library", "cli"),
    "ragas": ("library",),
    "trulens": ("library",),
    "garak": ("cli", "library"),
    "pyrit": ("library", "cli"),
    "giskard": ("library", "cli", "ci_app"),
    "openai-evals": ("library", "cli"),
    "lm-evaluation-harness": ("cli", "library"),
    "lmms-eval": ("cli", "library"),
    "lighteval": ("cli", "library"),
    "helm": ("cli", "library"),
    "promptbench": ("library",),
    "fuzzyai": ("cli", "library"),
    "agentic-security": ("cli", "library"),
    "ai-red-teaming-playground-labs": ("web_app",),
    "uqlm": ("library",),
    "autorag": ("library", "cli"),
    "safe-rlhf": ("library",),
    # Observability backends
    "langfuse": ("http_service", "library"),
    "langsmith": ("http_service", "library"),
    "helicone": ("proxy_gateway", "http_service", "library"),
    "arize-phoenix": ("http_service", "library"),
    "logfire": ("http_service", "library"),
    "openlit": ("http_service", "library"),
    "opik": ("http_service", "library"),
    "lmnr": ("http_service", "library"),
    "braintrust": ("http_service", "library"),
    "mlflow": ("http_service", "library", "cli"),
    "agenta": ("http_service", "library"),
    "pezzo": ("http_service", "library"),
    # Sandboxes / runtime isolation
    "modal": ("library", "cli"),
    "e2b": ("library", "http_service"),
    "daytona": ("cli", "http_service"),
    "nono": ("cli", "library"),
    # Workflow / low-code / platforms
    "flowise": ("web_app", "http_service"),
    "activepieces": ("web_app", "http_service"),
    "coze-loop": ("web_app", "http_service"),
    "comfyui": ("web_app", "desktop_app"),
    "agent-governance-toolkit": ("library", "cli"),
    "pathway-llm-app": ("library", "http_service"),
    "ragflow": ("http_service", "library"),
    "docetl": ("library", "cli"),
    # Browser / RPA
    "skyvern": ("library", "http_service"),
    "browser-use": ("library", "web_app"),
    # Honeypots / deception
    "beelzebub": ("http_service", "library"),
    # Explicit MCP servers (covered by regex for most, pin the borderline cases)
    "browser-mcp": ("mcp_server",),
    "mcp-playwright": ("mcp_server",),
    "mcp-server-browserbase": ("mcp_server", "library"),
    "playwright-mcp": ("mcp_server",),
    "magic-mcp": ("mcp_server",),
    "context-hub": ("mcp_server",),
    "mcp-toolbox": ("mcp_server",),
    # Prompt/workflow tooling
    "promptflow": ("library", "ide_plugin"),
    "promptmap": ("cli",),
    "manifest": ("library",),
}

# For rendering + the prompt rule: which surfaces count as pipeline-friendly?
PIPELINE_FRIENDLY: frozenset[str] = frozenset(
    {
        "cli",
        "library",
        "http_service",
        "mcp_server",
        "ci_app",
        "proxy_gateway",
    }
)


def _detect_integration_surfaces(data: dict) -> tuple[str, ...]:
    """Return integration surfaces for a tool node.

    Resolution order:
      1. The YAML's declared ``integration_surfaces`` field (source of truth
         once populated; the bulk-annotation script writes it).
      2. A per-id override in ``_SURFACE_OVERRIDES`` (used by the annotator
         to seed the YAML, and as a safety net for tools added after the
         last bulk pass).
      3. Regex heuristics over the free-text tagline / description /
         rationale. Precision-biased; returns ``()`` when uncertain.
    """
    declared = data.get("integration_surfaces")
    if isinstance(declared, list) and declared:
        return tuple(str(s) for s in declared)

    node_id = str(data.get("id") or "")
    if node_id in _SURFACE_OVERRIDES:
        return _SURFACE_OVERRIDES[node_id]

    text = " ".join(
        [
            str(data.get("name") or ""),
            str(data.get("tagline") or ""),
            str(data.get("description") or ""),
            str(data.get("inclusion_rationale") or ""),
        ]
    )
    seen: set[str] = set()
    out: list[str] = []
    for surface, pat in _SURFACE_RULES:
        if surface in seen:
            continue
        if pat.search(text):
            seen.add(surface)
            out.append(surface)
    return tuple(out)


@dataclass(frozen=True)
class NodeContext:
    """One retrieval hit, hydrated from disk, ready to render."""

    id: str
    type: str
    name: str
    snippet: str
    similarity: float
    # Tool-only facets. Empty/None for other node types.
    addresses_failure_modes: tuple[str, ...] = field(default_factory=tuple)
    control_paradigm: str | None = None
    temporal_phase: str | None = None
    autonomy_level: str | None = None
    integration_surfaces: tuple[str, ...] = field(default_factory=tuple)

    @property
    def url(self) -> str:
        prefix = NODE_TYPES.get(self.type, ("", ""))[1]
        return f"{prefix}/{self.id}" if prefix else ""


def _detect_type_and_path(node_id: str) -> tuple[str, Path] | None:
    for node_type, (subdir, _) in NODE_TYPES.items():
        for ext in (".yml", ".yaml"):
            candidate = DATA_DIR / subdir / f"{node_id}{ext}"
            if candidate.exists():
                return node_type, candidate
    return None


@lru_cache(maxsize=512)
def _load_node_yaml(node_id: str) -> tuple[str, dict] | None:
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
    if node_type == "paper":
        text = data.get("tldr") or data.get("notes") or data.get("title") or ""
    elif node_type == "incident":
        text = data.get("tagline") or data.get("description") or ""
    elif node_type == "taxonomy":
        text = data.get("scope") or ""
        if not text and isinstance(data.get("categories"), list):
            labels = [
                f"{c.get('external_id', '')}: {c.get('label', '')}"
                for c in data["categories"]
                if isinstance(c, dict)
            ]
            text = "; ".join(labels[:10])
    else:
        text = data.get("description") or data.get("tagline") or ""
    return str(text).strip()


def _extract_name(node_type: str, data: dict) -> str:
    if node_type in ("paper", "incident"):
        return str(data.get("title") or data.get("name") or data.get("id") or "")
    return str(data.get("name") or data.get("id") or "")


def hydrate(hits: Iterable[tuple[str, float]]) -> list[NodeContext]:
    out: list[NodeContext] = []
    for node_id, sim in hits:
        loaded = _load_node_yaml(node_id)
        if loaded is None:
            log.warning(
                "ask: retrieval hit %r did not resolve to a known node", node_id
            )
            continue
        node_type, data = loaded
        snippet = _extract_description(node_type, data)
        if len(snippet) > SNIPPET_CHARS:
            snippet = snippet[: SNIPPET_CHARS - 1].rstrip() + "…"

        kwargs: dict = dict(
            id=str(data.get("id") or node_id),
            type=node_type,
            name=_extract_name(node_type, data),
            snippet=snippet,
            similarity=float(sim),
        )
        if node_type == "tool":
            fms = data.get("addresses_failure_modes") or []
            if isinstance(fms, list):
                kwargs["addresses_failure_modes"] = tuple(str(x) for x in fms)
            kwargs["control_paradigm"] = data.get("control_paradigm") or None
            kwargs["temporal_phase"] = data.get("temporal_phase") or None
            kwargs["autonomy_level"] = data.get("autonomy_level") or None
            kwargs["integration_surfaces"] = _detect_integration_surfaces(data)

        out.append(NodeContext(**kwargs))
    return out


def _tool_facet_line(n: NodeContext) -> str:
    parts: list[str] = []
    if n.addresses_failure_modes:
        parts.append(f"addresses={','.join(n.addresses_failure_modes)}")
    if n.control_paradigm:
        parts.append(f"paradigm={n.control_paradigm}")
    if n.temporal_phase:
        parts.append(f"phase={n.temporal_phase}")
    if n.autonomy_level:
        parts.append(f"autonomy={n.autonomy_level}")
    if n.integration_surfaces:
        parts.append(f"surfaces={','.join(n.integration_surfaces)}")
    else:
        parts.append("surfaces=unknown")
    return "facets: " + " · ".join(parts) if parts else ""


def render_context_block(nodes: list[NodeContext]) -> str:
    if not nodes:
        return "(no context — retrieval returned zero hits)"
    lines: list[str] = []
    for n in nodes:
        header = f"[{n.id}] ({n.type}) {n.name}".rstrip()
        body_parts = [header]
        if n.type == "tool":
            facet_line = _tool_facet_line(n)
            if facet_line:
                body_parts.append(facet_line)
        body_parts.append(n.snippet or "(no description)")
        lines.append("\n".join(body_parts))
    return "\n\n---\n\n".join(lines)


PROMPT_TEMPLATE = """\
You are the SAICA-KG assistant. Answer using ONLY the KG node context below.

RULES — follow all, do not invent content:

1. Every factual claim cites a node id in brackets, e.g. "[pydantic-ai]".
   Never fabricate an id. Only cite ids that appear in the context block.

2. NAMING THE FAILURE MODE. If the question describes a phenomenon, name
   the most specific failure_mode node(s) that match, using their KG id.
   When a phenomenon spans multiple modes, say so and cite each — do not
   collapse to one.

3. COVERAGE GUARD. When you recommend a tool for a failure mode, the
   tool's `facets: addresses=…` list (shown in its context block) MUST
   contain that failure mode id. If no retrieved tool meets this bar,
   say "No tool in the retrieved context declares coverage for <mode>."
   Do not recommend a tool that lacks the declared coverage, even if its
   description sounds relevant.

4. AVOID CIRCULAR RECOMMENDATIONS. Tools whose paradigm is `recovery`
   and autonomy is `fully_autonomous` are themselves coding agents that
   self-recover; when the user wants to *supervise* an agent, prefer
   tools whose paradigm is `prevention` or `detection`, or whose
   autonomy is `graduated_hitl` / `full_hitl`. Flag explicitly when a
   retrieved candidate is "the agent itself, not a supervisor".

5. INTEGRATION-MODE FIT. {integration_rule}

6. BREADTH. When recommending tools, offer 2–3 options with a one-line
   rationale each (paradigm, phase, surface). Do not pick a single tool
   unless the retrieval genuinely contains only one qualifying match.

7. If the KG truly doesn't support an answer after applying these rules,
   say "The KG doesn't have this information."

Context:
{context_blocks}

Question: {question}
"""

INTEGRATION_RULE_PIPELINE = (
    "The user needs pipeline / API / headless integration. Prefer tools "
    "whose `surfaces` include any of: cli, library, http_service, "
    "mcp_server, ci_app, proxy_gateway. Avoid recommending ide_plugin, "
    "desktop_app, or web_app tools for the primary recommendation — if "
    "one appears in the retrieval and looks relevant, mention it only to "
    "explicitly flag that it is an IDE/hosted product and not "
    "pipeline-integratable."
)

INTEGRATION_RULE_NEUTRAL = (
    "The user did not specify an integration surface. Briefly note each "
    "recommended tool's surface (ide_plugin, cli, library, …) so the "
    "asker can judge fit."
)


def _wants_pipeline(question: str) -> bool:
    return bool(PIPELINE_INTENT_RE.search(question or ""))


def build_prompt(question: str, nodes: list[NodeContext]) -> str:
    rule = (
        INTEGRATION_RULE_PIPELINE
        if _wants_pipeline(question)
        else INTEGRATION_RULE_NEUTRAL
    )
    return PROMPT_TEMPLATE.format(
        context_blocks=render_context_block(nodes),
        question=question.strip(),
        integration_rule=rule,
    )


def hybrid_retrieve(
    question: str,
    k: int,
    *,
    find_similar,
    extra_pipeline_tools: int = 8,
) -> list[tuple[str, float]]:
    """Top-k retrieval with a pipeline-surface-biased supplement.

    When the question signals "I want to integrate this into a pipeline"
    (see :data:`PIPELINE_INTENT_RE`), the base top-k is frequently dominated
    by papers and IDE-hosted agents because those have the most "AI coding
    agent" vocabulary in their descriptions — squeezing out the headless
    libraries / CLIs / MCP servers / proxies that the question actually needs.

    We run a second, tool-only retrieval pass, filter to tools whose
    inferred integration surfaces are pipeline-friendly, and append up to
    ``extra_pipeline_tools`` that were not already in the base pool.
    """
    base: list[tuple[str, float]] = list(find_similar(question, k))
    if not _wants_pipeline(question):
        return base

    tool_hits = find_similar(question, k=max(k, 20), node_type="tool")
    seen = {nid for nid, _ in base}
    added: list[tuple[str, float]] = []
    for nid, sim in tool_hits:
        if nid in seen or len(added) >= extra_pipeline_tools:
            continue
        loaded = _load_node_yaml(nid)
        if loaded is None:
            continue
        _, data = loaded
        if set(_detect_integration_surfaces(data)) & PIPELINE_FRIENDLY:
            # Bias it to sit *after* the base hits but in similarity order.
            added.append((nid, sim))
            seen.add(nid)
    return base + added


__all__ = [
    "NODE_TYPES",
    "NodeContext",
    "PIPELINE_FRIENDLY",
    "build_prompt",
    "hybrid_retrieve",
    "hydrate",
    "render_context_block",
    "PROMPT_TEMPLATE",
    "_detect_integration_surfaces",
    "_wants_pipeline",
]
