"""``saica_preflight`` implementation.

Pure function. No MCP imports, no LLM call. Maps an action description to
candidate failure modes via keyword rules, then queries the KG for tools
that declare coverage for those modes and ranks them by paradigm fit,
surface fit, and stars.

The keyword rules are deliberately broad (precision-light, recall-heavy)
because preflight is a hot path: agents may call it dozens of times per
task, and a missed trigger silently degrades supervision while a
false-positive only adds an extra recommendation card. We err toward
flagging.
"""
from __future__ import annotations

import re
from typing import Optional

from pipeline.mcp._schemas_compat import (
    PreflightResult,
    Recommendation,
    Severity,
)
from pipeline.mcp.kg import iter_tools, tools_for_failure_mode

# ---------------------------------------------------------------------------
# Keyword → failure-mode rules
# ---------------------------------------------------------------------------
# Each entry is (compiled_regex, [failure_mode_ids]). Order matters only for
# the rationale (we list FMs in the order rules fired). Rules use word
# boundaries where the trigger is ambiguous in plain English.

_RULES: list[tuple[re.Pattern[str], list[str]]] = [
    # --- destructive shell / filesystem ----------------------------------
    (re.compile(r"\b(rm\b|delete\b|drop\s+table|drop\s+database|truncate\b|"
                r"unlink\b|rmdir\b)", re.IGNORECASE),
     ["cascading_failure", "incomplete_execution"]),

    # --- shell / subprocess execution ------------------------------------
    (re.compile(r"\b(shell\b|bash\b|sh\b|zsh\b|subprocess\.|os\.system|exec\b|"
                r"eval\(|run\s+command|system\()", re.IGNORECASE),
     ["security_vulnerability", "cascading_failure"]),

    # --- dependency installation -----------------------------------------
    # ``install <pkg>`` is treated as a supply-chain trigger even without a
    # package manager prefix; agents commonly say "install left-pad" rather
    # than "npm install left-pad". We err toward flagging — false-positives
    # only add a card; misses silently degrade supervision.
    (re.compile(r"\b(pip\s+install|npm\s+install|yarn\s+add|pnpm\s+add|"
                r"poetry\s+add|cargo\s+add|go\s+get|gem\s+install|brew\s+install|"
                r"uv\s+add|install\s+(?:dep|package|library|module|[a-z0-9][\w\-./@]*)|"
                r"add\s+dependency)\b",
                re.IGNORECASE),
     ["supply_chain_attack", "dependency_blindness"]),

    # --- network fetch ---------------------------------------------------
    (re.compile(r"\b(curl\b|wget\b|fetch\s+from\s+url|fetch\s+url|download\s+from|"
                r"requests\.get|urllib\.|http\s+(?:get|post)|webhook\s+payload)\b",
                re.IGNORECASE),
     ["supply_chain_attack", "context_pollution"]),

    # --- credentials / auth ----------------------------------------------
    (re.compile(r"\b(auth\b|token\b|secret\b|credential|api[_\-\s]?key|"
                r"private\s+key|oauth\b|bearer\b|password\b|\.env\b|"
                r"environment\s+variable)\b", re.IGNORECASE),
     ["security_vulnerability"]),

    # --- testing ---------------------------------------------------------
    (re.compile(r"\b(run\s+tests?|run\s+pytest|pytest\b|npm\s+test|jest\b|vitest\b|"
                r"mocha\b|go\s+test|cargo\s+test|test\s+suite)\b", re.IGNORECASE),
     ["test_manipulation"]),

    # --- VCS operations --------------------------------------------------
    (re.compile(r"\b(git\s+commit|git\s+push|git\s+merge|commit\b|push\b|"
                r"merge\b|open\s+pull\s+request|create\s+pr)\b", re.IGNORECASE),
     ["scope_creep"]),

    # --- file edits ------------------------------------------------------
    (re.compile(r"\b(edit\b|modify\b|change\b|rewrite\b|refactor\b|"
                r"patch\b|apply\s+diff|update\s+(?:file|function|class))\b",
                re.IGNORECASE),
     ["scope_creep", "logic_error"]),

    # --- third-party / external API call ---------------------------------
    (re.compile(r"\b(api\s+call|third[\-\s]?party|external\s+(?:service|api)|"
                r"call\s+(?:openai|anthropic|stripe|aws)|call\s+remote)\b",
                re.IGNORECASE),
     ["obsolescence", "fabrication"]),
]

# Words that escalate severity to "high" regardless of rule firing order.
_HIGH_RISK_RE = re.compile(
    r"\b(rm\b|rm\s+-rf|delete\b|drop\s+table|drop\s+database|--force\b|-f\b|"
    r"force[\-\s]push|shell\b|bash\b|subprocess\.|os\.system|exec\b)",
    re.IGNORECASE,
)

# Purely informational verbs → low risk if action ONLY contains these.
_LOW_RISK_RE = re.compile(
    r"^\s*(read|view|list|cat|ls|show|inspect|describe|grep|find|search|print)\b",
    re.IGNORECASE,
)

# ---------------------------------------------------------------------------
# agent_kind → preferred surfaces
# ---------------------------------------------------------------------------
_AGENT_SURFACE_PREFS: dict[str, tuple[str, ...]] = {
    "claude-code":   ("ide_plugin", "cli", "mcp_server", "library"),
    "cursor":        ("ide_plugin", "desktop_app", "library", "cli"),
    "windsurf":      ("ide_plugin", "desktop_app", "library", "cli"),
    "zed":           ("ide_plugin", "desktop_app", "library", "cli"),
    "aider":         ("cli", "library", "mcp_server"),
    "codex-cli":     ("cli", "library", "mcp_server"),
    "replit":        ("web_app", "library", "http_service"),
    "replit-agent":  ("web_app", "library", "http_service"),
}

_DEFAULT_SURFACE_PREFS: tuple[str, ...] = (
    "cli", "library", "mcp_server", "ci_app", "http_service",
)

# ---------------------------------------------------------------------------
# Classification
# ---------------------------------------------------------------------------

def classify_action(action: str) -> list[str]:
    """Return ordered, deduped failure-mode ids triggered by ``action``.

    Falls back to ``['scope_creep']`` (the most common FM in the KG) when no
    rule fires — preflight should always offer at least one supervisor.
    """
    if not action:
        return ["scope_creep"]
    seen: set[str] = set()
    out: list[str] = []
    for pattern, fms in _RULES:
        if pattern.search(action):
            for fm in fms:
                if fm not in seen:
                    seen.add(fm)
                    out.append(fm)
    if not out:
        out.append("scope_creep")
    return out


def assess_severity(action: str) -> Severity:
    """High if destructive / shell, low if pure read, medium otherwise."""
    if not action:
        return "medium"
    if _HIGH_RISK_RE.search(action):
        return "high"
    if _LOW_RISK_RE.search(action):
        return "low"
    return "medium"


def _surface_prefs(agent_kind: Optional[str]) -> tuple[str, ...]:
    if not agent_kind:
        return _DEFAULT_SURFACE_PREFS
    return _AGENT_SURFACE_PREFS.get(agent_kind.lower().strip(), _DEFAULT_SURFACE_PREFS)


def _rank_key(
    doc: dict,
    *,
    paradigm_pref: str = "prevention",
    surface_prefs: tuple[str, ...] = _DEFAULT_SURFACE_PREFS,
) -> tuple[int, int, int]:
    """Sort key — higher is better; we negate in the sorted() call.

    Primary: paradigm match (prevention preferred for pre-action advice).
    Secondary: best-rank surface match (lower index = more preferred).
    Tertiary: stars.
    """
    paradigm = (doc.get("control_paradigm") or "").lower()
    paradigm_score = 1 if paradigm == paradigm_pref else 0

    surfaces = doc.get("integration_surfaces") or []
    if isinstance(surfaces, list):
        surface_set = {str(s).lower() for s in surfaces}
    else:
        surface_set = set()
    # 0 = no preferred surface; otherwise len(prefs) - index, so earlier
    # entries score higher.
    surface_score = 0
    for idx, s in enumerate(surface_prefs):
        if s in surface_set:
            surface_score = len(surface_prefs) - idx
            break

    try:
        stars = int(doc.get("stars") or 0)
    except (TypeError, ValueError):
        stars = 0
    return (paradigm_score, surface_score, stars)


def _to_recommendation(doc: dict, *, fm_id: str) -> Recommendation:
    tid = str(doc.get("id") or "")
    surfaces = doc.get("integration_surfaces") or []
    surface_list = [str(s) for s in surfaces] if isinstance(surfaces, list) else []
    fms = doc.get("addresses_failure_modes") or []
    fm_list = [str(f) for f in fms] if isinstance(fms, list) else []

    paradigm = str(doc.get("control_paradigm") or "prevention")
    surface_blurb = "/".join(surface_list[:3]) if surface_list else "unknown surface"
    why = (
        f"{doc.get('name') or tid} declares {paradigm} coverage for "
        f"{fm_id} via {surface_blurb}."
    )
    try:
        stars = int(doc.get("stars") or 0) or None
    except (TypeError, ValueError):
        stars = None
    return Recommendation(
        tool_id=tid,
        tool_name=str(doc.get("name") or tid),
        why=why,
        paradigm=paradigm,  # type: ignore[arg-type]  # validated by Pydantic Literal
        temporal_phase=str(doc.get("temporal_phase") or ""),
        autonomy_level=str(doc.get("autonomy_level") or ""),
        integration_surfaces=surface_list,
        addresses_failure_modes=fm_list,
        stars=stars,
        url=f"/tools/{tid}",
    )


def recommend_supervisors(
    fm_ids: list[str],
    *,
    agent_kind: Optional[str] = None,
    limit: int = 3,
) -> list[Recommendation]:
    """Pick up to ``limit`` distinct supervisor tools across ``fm_ids``."""
    surface_prefs = _surface_prefs(agent_kind)
    seen_ids: set[str] = set()
    out: list[Recommendation] = []

    # Round-robin across FMs so each gets at least one pick before we top up.
    per_fm: dict[str, list[dict]] = {}
    for fm in fm_ids:
        candidates = tools_for_failure_mode(fm)
        candidates.sort(
            key=lambda d: _rank_key(d, surface_prefs=surface_prefs),
            reverse=True,
        )
        per_fm[fm] = candidates

    # First pass: one per FM.
    for fm in fm_ids:
        if len(out) >= limit:
            break
        for doc in per_fm.get(fm, []):
            tid = str(doc.get("id") or "")
            if tid and tid not in seen_ids:
                seen_ids.add(tid)
                out.append(_to_recommendation(doc, fm_id=fm))
                break

    # Top-up pass: fill remaining slots with best-overall.
    if len(out) < limit:
        pool: list[tuple[tuple[int, int, int], dict, str]] = []
        for fm, candidates in per_fm.items():
            for doc in candidates:
                tid = str(doc.get("id") or "")
                if tid and tid not in seen_ids:
                    pool.append((_rank_key(doc, surface_prefs=surface_prefs), doc, fm))
        pool.sort(key=lambda x: x[0], reverse=True)
        for _, doc, fm in pool:
            if len(out) >= limit:
                break
            tid = str(doc.get("id") or "")
            if tid not in seen_ids:
                seen_ids.add(tid)
                out.append(_to_recommendation(doc, fm_id=fm))

    return out


def saica_preflight(
    action: str,
    context: Optional[str] = None,
    agent_kind: Optional[str] = None,
) -> PreflightResult:
    """Pre-action supervision advice for a proposed agent action."""
    if action is None:
        action = ""
    # ``context`` is currently unused for classification — reserved for a
    # future LLM-assisted classifier. We still let callers pass it so the
    # contract is stable.
    _ = context

    fm_ids = classify_action(action)
    severity = assess_severity(action)
    recs = recommend_supervisors(fm_ids, agent_kind=agent_kind)

    surfaces_used = sorted({s for r in recs for s in r.integration_surfaces})
    surface_blurb = ", ".join(surfaces_used[:4]) if surfaces_used else "no clear surface"
    fm_blurb = ", ".join(fm_ids[:3])
    action_blurb = (action or "this action").strip()
    if len(action_blurb) > 80:
        action_blurb = action_blurb[:77] + "..."
    rationale = (
        f"{action_blurb!r} may trigger {fm_blurb}; "
        f"recommended supervisors expose {surface_blurb}."
    )

    return PreflightResult(
        risk_failure_modes=fm_ids,
        overall_risk=severity,
        recommended_supervisors=recs,
        rationale=rationale,
    )


# Used by tests + sanity checks; keeps every helper available for re-use.
def all_supervision_tools() -> list[dict]:
    return list(iter_tools())


__all__ = [
    "all_supervision_tools",
    "assess_severity",
    "classify_action",
    "recommend_supervisors",
    "saica_preflight",
]
