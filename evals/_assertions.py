"""Assertion helpers used by promptfoo's `python:` assertion type.

Cited KG nodes:
  - data/tools/promptfoo.yml — the supervisor we install (CLI + ci_app surface).
  - data/failure_modes/*.yml — the canonical 11-FM list these checks defend.

These helpers are intentionally stdlib-only (no extra Python deps in CI). Each
function returns a dict in promptfoo's `GradingResult` shape::

    {"pass": bool, "score": float, "reason": str}

promptfoo invokes them per test row by passing the model output and the test
context. Most of our static-data checks ignore both inputs and just walk the
on-disk fixtures (recommendations.json + data/tools/ + data/failure_modes/).

We keep the heavy I/O (directory listings, JSON parse) inside one
`@functools.lru_cache`'d loader so the suite stays fast even if every single
test calls the helpers.
"""

from __future__ import annotations

import functools
import json
import os
from pathlib import Path

# ---------------------------------------------------------------------------
# Locate repo root from this file (evals/_assertions.py → repo root is parent).
# This keeps helpers usable both when promptfoo runs from the repo root and
# when CI uses a different cwd.
# ---------------------------------------------------------------------------

_REPO_ROOT = Path(__file__).resolve().parent.parent


def _root() -> Path:
    # promptfoo sometimes sets PROMPTFOO_CWD; honour it if present so tests
    # are runnable from arbitrary working directories without surprise.
    env = os.environ.get("SAICA_REPO_ROOT")
    return Path(env) if env else _REPO_ROOT


@functools.lru_cache(maxsize=1)
def load_recommendations() -> dict:
    """Read recommendations.json from the repo root, cached for the run."""
    path = _root() / "recommendations.json"
    with path.open("r", encoding="utf-8") as fh:
        return json.load(fh)


@functools.lru_cache(maxsize=1)
def load_known_tool_ids() -> frozenset[str]:
    """Every `<id>.yml` under data/tools/ (id == filename stem)."""
    tools_dir = _root() / "data" / "tools"
    return frozenset(p.stem for p in tools_dir.glob("*.yml"))


@functools.lru_cache(maxsize=1)
def load_known_failure_modes() -> frozenset[str]:
    """Canonical SAICA failure-mode ids (filename stems under data/failure_modes/)."""
    fm_dir = _root() / "data" / "failure_modes"
    return frozenset(p.stem for p in fm_dir.glob("*.yml"))


# Coding-agent ids that should never appear *as* a recommended supervisor for
# a peer agent — agents are alternatives to each other, not supervisors of
# each other. The set is exactly the keys under recommendations.by_agent.
@functools.lru_cache(maxsize=1)
def peer_agent_ids() -> frozenset[str]:
    return frozenset(load_recommendations().get("by_agent", {}).keys())


def _all_recommendation_blocks() -> list[tuple[str, dict]]:
    """Yield ``(label, tier_block)`` for every tier across agnostic + by_agent."""
    rec = load_recommendations()
    out: list[tuple[str, dict]] = []
    for tier_name, tier in (rec.get("agnostic") or {}).items():
        out.append((f"agnostic/{tier_name}", tier))
    for agent_id, tiers in (rec.get("by_agent") or {}).items():
        for tier_name, tier in (tiers or {}).items():
            out.append((f"by_agent/{agent_id}/{tier_name}", tier))
    return out


# ---------------------------------------------------------------------------
# Assertion bodies. Each returns a GradingResult-shaped dict. These are
# referenced from YAML via `value: file://evals/_assertions.py:assert_<name>`.
# (Path is resolved relative to the promptfoo config file — the repo root.)
# ---------------------------------------------------------------------------


def _ok(reason: str = "ok") -> dict:
    return {"pass": True, "score": 1.0, "reason": reason}


def _fail(reason: str) -> dict:
    return {"pass": False, "score": 0.0, "reason": reason}


def assert_tool_ids_resolve(output, context):  # noqa: ARG001 — promptfoo signature
    """Every tool_id under any recommendation tier must exist in data/tools/."""
    known = load_known_tool_ids()
    missing: list[str] = []
    for label, tier in _all_recommendation_blocks():
        for tool in tier.get("tools", []) or []:
            tid = tool.get("tool_id")
            if tid and tid not in known:
                missing.append(f"{label}: {tid}")
    if missing:
        return _fail(f"unknown tool_ids: {sorted(set(missing))[:8]}")
    return _ok(f"all tool_ids resolve ({len(known)} known)")


def assert_failure_modes_canonical(output, context):  # noqa: ARG001
    """Every failure_mode mentioned must be one of the 11 canonical ids."""
    known = load_known_failure_modes()
    bad: list[str] = []
    for label, tier in _all_recommendation_blocks():
        for fm in tier.get("covered_failure_modes", []) or []:
            if fm not in known:
                bad.append(f"{label}.covered:{fm}")
        for fm in tier.get("uncovered_failure_modes", []) or []:
            if fm not in known:
                bad.append(f"{label}.uncovered:{fm}")
        for tool in tier.get("tools", []) or []:
            for fm in tool.get("addresses_failure_modes", []) or []:
                if fm not in known:
                    bad.append(f"{label}.{tool.get('tool_id')}:{fm}")
    if bad:
        return _fail(f"non-canonical failure_modes: {sorted(set(bad))[:8]}")
    return _ok(f"all failure_modes canonical ({len(known)} known)")


def assert_blocklist_honoured(output, context):  # noqa: ARG001
    """No id on the blocklist may appear as a recommended tool."""
    rec = load_recommendations()
    block = set(rec.get("blocklist") or [])
    leaks: list[str] = []
    for label, tier in _all_recommendation_blocks():
        for tool in tier.get("tools", []) or []:
            if tool.get("tool_id") in block:
                leaks.append(f"{label}:{tool.get('tool_id')}")
    if leaks:
        return _fail(f"blocklisted ids leaked into recommendations: {leaks}")
    return _ok(f"blocklist honoured ({sorted(block)})")


def assert_no_peer_agents_recommended(output, context):  # noqa: ARG001
    """When `agent_kind` is set, recommended tools must not be peer agents.

    A peer agent is any id that appears as a key in `by_agent` — those are
    coding agents that compete with one another, not supervisors of each
    other. SAICA's MECE story breaks if we tell a Cursor user to install
    Cline.
    """
    peers = peer_agent_ids()
    leaks: list[str] = []
    for label, tier in _all_recommendation_blocks():
        if not tier.get("agent_kind"):
            continue
        ak = tier["agent_kind"]
        for tool in tier.get("tools", []) or []:
            tid = tool.get("tool_id")
            if tid in peers:
                leaks.append(f"{label}(agent_kind={ak}) -> peer {tid}")
    if leaks:
        return _fail(f"peer-agent contamination: {leaks}")
    return _ok(f"no peer-agent contamination (checked {len(peers)} peer ids)")


def assert_optimal_claude_code_coverage(output, context):  # noqa: ARG001
    """Optimal tier for claude-code should cover >= 8 of 11 failure modes."""
    rec = load_recommendations()
    block = (rec.get("by_agent") or {}).get("claude-code", {}).get("optimal")
    if not block:
        return _fail("by_agent/claude-code/optimal missing")
    n = len(block.get("covered_failure_modes") or [])
    if n < 8:
        return _fail(f"claude-code optimal covers only {n}/11 FMs (want ≥ 8)")
    return _ok(f"claude-code optimal covers {n}/11 FMs")


def assert_full_tier_coverage_complete(output, context):  # noqa: ARG001
    """Every full-tier block (agnostic + per-agent) must have coverage_complete=True."""
    bad: list[str] = []
    rec = load_recommendations()
    full = (rec.get("agnostic") or {}).get("full")
    if not full or not full.get("coverage_complete"):
        bad.append("agnostic/full")
    for agent_id, tiers in (rec.get("by_agent") or {}).items():
        f = (tiers or {}).get("full") or {}
        if not f.get("coverage_complete"):
            bad.append(f"by_agent/{agent_id}/full")
    if bad:
        return _fail(f"full tier missing coverage_complete: {bad}")
    return _ok("all full tiers report coverage_complete=true")


def assert_minimum_tier_one_tool(output, context):  # noqa: ARG001
    """The minimum tier must always recommend exactly one tool."""
    bad: list[str] = []
    rec = load_recommendations()
    mn = (rec.get("agnostic") or {}).get("minimum") or {}
    if len(mn.get("tools") or []) != 1:
        bad.append(f"agnostic/minimum has {len(mn.get('tools') or [])} tools")
    for agent_id, tiers in (rec.get("by_agent") or {}).items():
        m = (tiers or {}).get("minimum") or {}
        n = len(m.get("tools") or [])
        if n != 1:
            bad.append(f"by_agent/{agent_id}/minimum has {n} tools")
    if bad:
        return _fail(f"minimum tier wrong size: {bad}")
    return _ok("every minimum tier returns exactly 1 tool")


# ---------------------------------------------------------------------------
# Helpers reused by ask_probe.yaml — invoked from inline `python:` assertions.
# ---------------------------------------------------------------------------


def assert_answer_cites_known_ids(output, context):  # noqa: ARG001
    """Every bracketed [id] in the answer must resolve to a known tool or FM."""
    import re

    if not isinstance(output, str):
        return _fail(f"non-string output: {type(output).__name__}")
    known = load_known_tool_ids() | load_known_failure_modes()
    cited = set(re.findall(r"\[([a-z0-9][a-z0-9_-]{1,60})\]", output))
    bogus = sorted(c for c in cited if c not in known)
    if bogus:
        return _fail(f"answer fabricates ids: {bogus}")
    return _ok(f"all {len(cited)} cited ids resolve")


# ---------------------------------------------------------------------------
# Live /ask probe — gated on ASK_API env var. We deliberately make the
# HTTP call from inside the assertion (rather than promptfoo's `http`
# provider) so the suite can `pass: True, reason: skipped` cleanly when
# ASK_API is unset, without spurious network errors. promptfoo has no
# top-level `skip:` field as of v0.121.
# ---------------------------------------------------------------------------


def _ask(question: str) -> tuple[str, dict]:
    """POST {question} to $ASK_API and return (answer_text, full_json).

    Returns ("", {}) and is the caller's job to surface — this helper does
    not raise on HTTP errors so a stuck backend reports a clean assertion
    failure instead of a Python traceback.
    """
    import json as _json
    import urllib.error
    import urllib.request

    url = os.environ.get("ASK_API", "").strip()
    if not url:
        return "", {}
    body = _json.dumps({"question": question}).encode("utf-8")
    req = urllib.request.Request(  # noqa: S310 — trusted dev URL
        url,
        data=body,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=60) as resp:  # noqa: S310
            payload = _json.loads(resp.read().decode("utf-8"))
    except (urllib.error.URLError, TimeoutError, ValueError) as exc:
        return "", {"_error": f"{type(exc).__name__}: {exc}"}
    return str(payload.get("answer") or ""), payload


def _ask_or_skip(question: str):
    """Return (answer, payload) or a GradingResult dict to short-circuit."""
    if not os.environ.get("ASK_API", "").strip():
        return _ok("skipped: ASK_API unset")
    answer, payload = _ask(question)
    if "_error" in payload:
        return _fail(f"/ask call failed: {payload['_error']}")
    if not answer:
        return _fail("/ask returned empty answer")
    return answer, payload


def assert_ask_recommends_supervisor(output, context):  # noqa: ARG001
    """Live: ask for a scope_creep supervisor; expect a known supervisor id."""
    res = _ask_or_skip(
        "What tool prevents scope_creep in a Python pipeline using GitHub Actions?",
    )
    if isinstance(res, dict):
        return res
    answer, _ = res
    expected_any = ("semgrep", "promptfoo", "langgraph", "guardrails-ai")
    low = answer.lower()
    if not any(name in low for name in expected_any):
        return _fail(
            f"answer mentions none of {expected_any}; got: {answer[:200]!r}",
        )
    # Also assert no fabricated ids.
    cite_check = assert_answer_cites_known_ids(answer, None)
    if not cite_check["pass"]:
        return cite_check
    return _ok("recommends a known supervisor and cites only known ids")


def assert_ask_distinguishes_failure_modes(output, context):  # noqa: ARG001
    """Live: ask the FM-vs-FM question; expect both ids, no third FM fabricated."""
    res = _ask_or_skip(
        "What's the difference between fabrication and obsolescence?",
    )
    if isinstance(res, dict):
        return res
    answer, _ = res
    low = answer.lower()
    if "fabrication" not in low or "obsolescence" not in low:
        return _fail(
            "answer must mention both 'fabrication' and 'obsolescence'; "
            f"got: {answer[:200]!r}",
        )
    cite_check = assert_answer_cites_known_ids(answer, None)
    if not cite_check["pass"]:
        return cite_check
    return _ok("answer distinguishes both FMs without fabrication")
