"""Rater B — deterministic keyword-rule fault classifier.

Independent of Kimi. Uses :mod:`pipeline.nlp.keywords`'s
``FAILURE_MODE_KEYWORDS`` augmented with a small, purpose-built rule set for
ControlParadigm and TemporalPhase decisions. Rules are documented inline.

Design principles:

- No ML, no LLM. Pure regex + keyword match.
- Emits the same ``FaultClassification``-shaped dict as Rater A so the two
  can be passed to ``sklearn.metrics.cohen_kappa_score`` without adapters.
- Tuned to the SAICA-KG FailureMode semantics, NOT to perfectly agree with
  Kimi — the κ would be trivially 1.0 if both raters were mirrors.
- Falls back to null / empty when no rule fires, with low confidence.
"""

from __future__ import annotations

import re
from dataclasses import asdict, dataclass
from typing import Optional

from pipeline.nlp.keywords import FAILURE_MODE_KEYWORDS
from pipeline.nlp.preprocess import keyword_hits


# ---------------------------------------------------------------------------
# Extended FailureMode keyword map
#
# pipeline/nlp/keywords.py is tuned for supervision-tool discovery (phrases
# like "slopsquatting", "memory poisoning"). Real fault descriptions use
# plainer language ("NoneType", "import error", "auth bypass"). We extend
# the map here instead of mutating the tool-discovery module.
# ---------------------------------------------------------------------------

EXTRA_FAILURE_MODE_KEYWORDS: dict[str, list[str]] = {
    "fabrication": [
        "non-existent", "does not exist", "undefined", "nonetype",
        "attribute error", "attributeerror", "no attribute",
        "no such file", "filenotfounderror",
    ],
    "obsolescence": [
        "deprecated", "removed", "no longer supported", "upgrade",
        "upstream change", "api change", "backward compat", "backward-compat",
        "schema drift", "retired",
    ],
    "logic_error": [
        "incorrect logic", "wrong behaviour", "wrong behavior", "bug",
        "parsing", "invalid", "malformed", "null",
        "incoherent", "inconsistent", "race condition",
        "nan", "type mismatch", "typeerror", "type error",
        "valueerror", "mismatched", "inconsistency",
    ],
    "security_vulnerability": [
        "authentication", "auth bypass", "authorization", "credential",
        "access control", "permission", "secret", "api key",
        "token leak", "cve-", "injection", "memory leak",
        "unsafe", "security",
    ],
    "context_pollution": [
        "context overflow", "context window", "token tracking",
        "token counter", "token count", "context loss",
        "state inconsistency", "state management", "state tracking",
        "state corrupt", "memory poisoning", "history",
        "lost the mapping", "temporal inconsistency",
    ],
    "supply_chain_attack": [
        "malicious", "typosquat", "slopsquat", "compromised",
        "supply chain",
    ],
    "cascading_failure": [
        "cascade", "cascading", "propagate", "propagation",
        "downstream", "spiral", "compounding",
    ],
    "incomplete_execution": [
        "not execut", "did not run", "stopped", "terminat",
        "premature", "infinite loop", "prevented", "abort",
        "skipped",
    ],
    "test_manipulation": [
        "disable test", "skip test", "pytest.mark.skip",
        "comment out", "weaken assert",
    ],
    "scope_creep": [
        "unauthorized", "out of scope", "beyond", "unsanctioned",
    ],
    "dependency_blindness": [
        "reinvent", "duplicate implementation", "reimplement",
    ],
}


def _merged_keywords() -> dict[str, list[str]]:
    merged: dict[str, list[str]] = {}
    for fm, ks in FAILURE_MODE_KEYWORDS.items():
        merged[fm] = list(ks)
    for fm, extras in EXTRA_FAILURE_MODE_KEYWORDS.items():
        merged.setdefault(fm, [])
        merged[fm].extend(extras)
    return merged


MERGED_KEYWORDS = _merged_keywords()


def _compile_merged() -> dict[str, list[tuple[str, re.Pattern[str]]]]:
    compiled: dict[str, list[tuple[str, re.Pattern[str]]]] = {}
    for fm, phrases in MERGED_KEYWORDS.items():
        entries: list[tuple[str, re.Pattern[str]]] = []
        for phrase in phrases:
            escaped = re.escape(phrase)
            escaped = re.sub(r"\\\s+", r"\\s+", escaped)
            pat = re.compile(rf"(?<!\w){escaped}(?!\w)", re.IGNORECASE)
            entries.append((phrase, pat))
        compiled[fm] = entries
    return compiled


_MERGED_PATTERNS = _compile_merged()


def _merged_hits(text: str) -> dict[str, list[str]]:
    hits: dict[str, list[str]] = {}
    low = text  # patterns are case-insensitive
    for fm, entries in _MERGED_PATTERNS.items():
        matched: list[str] = []
        for phrase, pat in entries:
            if pat.search(low):
                matched.append(phrase)
        if matched:
            hits[fm] = matched
    return hits


# ---------------------------------------------------------------------------
# TemporalPhase rules
#
# Surface-only: we look for phase-anchor phrases. In ambiguous cases we
# prefer null over a guess (explicit in the study design).
# ---------------------------------------------------------------------------

TEMPORAL_PHASE_RULES: dict[str, list[str]] = {
    "pre_generation": [
        "install", "installation", "build", "setup", "configure",
        "configuration", "misconfiguration", "dependency", "depend",
        "import", "module", "package", "environment", "env ",
        "initialise", "initialize", "provision", "path",
        "platform", "credentials loading", "credential",
        "authentication", "authorization", "startup", "bootstrap",
        "resolver", "lockfile",
    ],
    "in_generation": [
        "prompt", "token", "context window", "streaming", "stream",
        "reasoning", "tokeniser", "tokenizer", "generation",
        "output format", "structured output", "tool call",
        "tool-call", "tool calling", "tool-calling",
        "response format", "llm", "model response",
    ],
    "post_generation": [
        "execution", "execute", "tool invocation", "invoke",
        "state persistence", "persist", "database", "file system",
        "filesystem", "filename", "write", "save", "store",
        "downstream", "after the response", "runtime", "crash",
        "exception", "rendering", "ui", "logging",
    ],
}


def classify_temporal_phase(text: str) -> tuple[Optional[str], float, list[str]]:
    """Score each phase by keyword hits; return top with margin-based confidence.

    Returns ``(phase_or_None, confidence, evidence)``. Confidence is:
    * 0.75 when the top phase's score >= 2 × the runner-up
    * 0.55 when the top is strictly greater
    * 0.30 (null) when no phase hit at all
    """
    hits: dict[str, list[str]] = {k: [] for k in TEMPORAL_PHASE_RULES}
    low = text.lower()
    for phase, kws in TEMPORAL_PHASE_RULES.items():
        for kw in kws:
            # simple substring test — these are short, intentional phrases
            if kw in low:
                hits[phase].append(kw)
    scored = [(phase, len(v)) for phase, v in hits.items()]
    scored.sort(key=lambda x: -x[1])
    if scored[0][1] == 0:
        return None, 0.3, []
    top_phase, top = scored[0]
    runner_up = scored[1][1] if len(scored) > 1 else 0
    if runner_up == 0:
        conf = 0.8
    elif top >= 2 * runner_up:
        conf = 0.75
    elif top > runner_up:
        conf = 0.55
    else:
        # Tie — prefer null.
        return None, 0.35, []
    return top_phase, conf, hits[top_phase][:4]


# ---------------------------------------------------------------------------
# ControlParadigm rules
#
# Fault descriptions rarely name the supervision regime explicitly; we use a
# heuristic mapping from surface markers of fault *stage* and *reversibility*
# to the regime that would most naturally address them.
# ---------------------------------------------------------------------------

CONTROL_PARADIGM_RULES: dict[str, list[str]] = {
    "prevention": [
        "prevent", "validation", "validate", "schema check",
        "type check", "pin", "lockfile", "ahead of time",
        "configuration error", "misconfiguration", "installation",
        "missing credential", "missing dependency", "import error",
    ],
    "detection": [
        "detect", "log", "logging", "trace", "tracing", "monitor",
        "telemetry", "observability", "silent", "suppressed",
        "swallowed", "undetected", "unreported",
    ],
    "correction": [
        "correct", "fix", "patch", "rerun", "retry", "auto-retry",
        "repair", "reroute", "fallback",
    ],
    "recovery": [
        "recover", "recovery", "fallback", "roll back", "rollback",
        "restart", "restore", "resume", "crash", "terminate",
        "aborted", "aborting",
    ],
}


def classify_control_paradigm(text: str) -> tuple[Optional[str], float, list[str]]:
    """Score each paradigm by keyword hits; return top with margin-based confidence."""
    hits: dict[str, list[str]] = {k: [] for k in CONTROL_PARADIGM_RULES}
    low = text.lower()
    for para, kws in CONTROL_PARADIGM_RULES.items():
        for kw in kws:
            if kw in low:
                hits[para].append(kw)
    scored = [(para, len(v)) for para, v in hits.items()]
    scored.sort(key=lambda x: -x[1])
    if scored[0][1] == 0:
        return None, 0.3, []
    top_para, top = scored[0]
    runner_up = scored[1][1] if len(scored) > 1 else 0
    if runner_up == 0:
        conf = 0.7
    elif top >= 2 * runner_up:
        conf = 0.65
    elif top > runner_up:
        conf = 0.5
    else:
        return None, 0.35, []
    return top_para, conf, hits[top_para][:4]


# ---------------------------------------------------------------------------
# FailureMode rules (multi-label)
# ---------------------------------------------------------------------------


def classify_failure_modes(text: str) -> tuple[list[str], float, list[str]]:
    """Return every FailureMode id with >=1 keyword hit.

    Confidence is: 0.75 when >=3 distinct modes hit, 0.6 when 1–2, 0.3 when 0.
    """
    hits = _merged_hits(text)
    # Also pull in pipeline/nlp/preprocess.keyword_hits (original set) for
    # robustness — any hit counts.
    pipeline_hits = keyword_hits(text)
    for fm, kws in pipeline_hits.items():
        hits.setdefault(fm, [])
        for kw in kws:
            if kw not in hits[fm]:
                hits[fm].append(kw)

    modes = sorted(hits.keys())
    if not modes:
        return [], 0.3, []
    evidence: list[str] = []
    for fm in modes:
        if hits[fm]:
            evidence.append(f"{fm}:{hits[fm][0]}")
    if len(modes) >= 3:
        conf = 0.75
    else:
        conf = 0.6
    return modes, conf, evidence[:5]


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------


@dataclass
class RaterBClassification:
    control_paradigm: Optional[str]
    control_paradigm_confidence: float
    temporal_phase: Optional[str]
    temporal_phase_confidence: float
    failure_modes: list[str]
    failure_modes_confidence: float
    evidence: list[str]

    def to_dict(self) -> dict:
        return asdict(self)


def classify_fault_rules(description: str) -> RaterBClassification:
    """Classify ONE fault description with the rule engine."""
    cp, cp_conf, cp_ev = classify_control_paradigm(description)
    tp, tp_conf, tp_ev = classify_temporal_phase(description)
    modes, modes_conf, mode_ev = classify_failure_modes(description)
    return RaterBClassification(
        control_paradigm=cp,
        control_paradigm_confidence=cp_conf,
        temporal_phase=tp,
        temporal_phase_confidence=tp_conf,
        failure_modes=modes,
        failure_modes_confidence=modes_conf,
        evidence=(cp_ev + tp_ev + mode_ev)[:8],
    )


__all__ = [
    "CONTROL_PARADIGM_RULES",
    "EXTRA_FAILURE_MODE_KEYWORDS",
    "RaterBClassification",
    "TEMPORAL_PHASE_RULES",
    "classify_control_paradigm",
    "classify_failure_modes",
    "classify_fault_rules",
    "classify_temporal_phase",
]
