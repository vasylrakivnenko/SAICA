"""Checks behind ``tests/test_recommendations_file.py`` and the live
``/api/ask`` probes.

Two groups:

* **File checks** (no model, no network): every tool id and failure-mode
  id in ``recommendations.json`` exists in the KG, and no tool is listed
  for a mode on which SAICA-Bench measured it below the floor. They are
  plain functions that return a list of problems; pytest runs them. They
  test files, not model behaviour.
* **Live probes** of the Ask endpoint. These do test a model, cost money,
  and run only when ``ASK_API`` is set. In pytest an unset ``ASK_API`` is
  a *skip*. Through promptfoo (which has no "skipped" result) it is a
  *fail* with the reason "not run": a probe that did not run never
  reports a pass.

Needs only `requests` and the project's own loaders.
"""

from __future__ import annotations

import os
import re
from typing import Any, Iterator

# ---------------------------------------------------------------------------
# File checks on recommendations.json
# ---------------------------------------------------------------------------


def iter_recommendations(
    node: Any, mode: str | None = None, where: str = ""
) -> Iterator[tuple[str, str | None, dict]]:
    """Yield ``(where, failure mode or None, recommendation dict)`` for
    every dict with a ``tool_id`` anywhere in a payload. ``mode`` is the
    enclosing ``by_failure_mode`` key, when there is one. The
    ``not_listed`` table (pairs the floor removed) is not a listing."""
    if isinstance(node, dict):
        if isinstance(node.get("tool_id"), str):
            yield where, mode, node
        inside_modes = where.endswith("by_failure_mode")
        for key, value in node.items():
            if key == "not_listed":
                continue
            yield from iter_recommendations(
                value,
                key if inside_modes else mode,
                f"{where}/{key}" if where else str(key),
            )
    elif isinstance(node, list):
        for item in node:
            yield from iter_recommendations(item, mode, where)


def unknown_tool_ids(payload: dict, tool_ids: frozenset[str] | set[str]) -> list[str]:
    """Listed tools that are not in the KG."""
    return sorted(
        {
            f"{where}: {rec['tool_id']}"
            for where, _, rec in iter_recommendations(payload)
            if rec["tool_id"] not in tool_ids
        }
    )


def unknown_failure_modes(
    payload: dict, mode_ids: frozenset[str] | set[str] | tuple[str, ...]
) -> list[str]:
    """Failure-mode ids used anywhere in the payload that the KG lacks."""
    known = set(mode_ids)
    bad: set[str] = set()

    def visit(node: Any, where: str) -> None:
        if isinstance(node, dict):
            for key in (
                "addresses_failure_modes",
                "covered_failure_modes",
                "uncovered_failure_modes",
            ):
                for fm in node.get(key) or []:
                    if fm not in known:
                        bad.add(f"{where}/{key}: {fm}")
            for key in ("by_failure_mode", "priorities", "measured_j"):
                table = node.get(key)
                if isinstance(table, dict):
                    bad.update(
                        f"{where}/{key}: {fm}" for fm in table if fm not in known
                    )
            for key, value in node.items():
                visit(value, f"{where}/{key}" if where else str(key))
        elif isinstance(node, list):
            for item in node:
                visit(item, where)

    visit(payload, "")
    return sorted(bad)


def below_floor_pairs(
    payload: dict,
    below_floor: dict[str, dict[str, float]],
    archived: set[str] | frozenset[str] = frozenset(),
) -> list[str]:
    """Listed tool × mode pairs that the measured floor forbids.

    ``below_floor`` is ``{tool id: {failure mode: best measured J}}`` for
    the pairs measured below the floor; ``archived`` are tools that may
    not be listed at all.
    """
    problems: set[str] = set()
    for where, mode, rec in iter_recommendations(payload):
        tool_id = rec["tool_id"]
        if tool_id in archived:
            problems.add(f"{where}: {tool_id} is archived")
        listed = set(rec.get("addresses_failure_modes") or []) | (
            {mode} if mode else set()
        )
        for fm in sorted(listed & set(below_floor.get(tool_id, {}))):
            problems.add(
                f"{where}: {tool_id} for {fm} (J {below_floor[tool_id][fm]:+.2f})"
            )
    return sorted(problems)


# ---------------------------------------------------------------------------
# Live probes of the Ask endpoint
# ---------------------------------------------------------------------------

SCOPE_CREEP_QUESTION = (
    "What tool prevents scope_creep in a Python pipeline using GitHub Actions?"
)
TWO_MODES_QUESTION = "What's the difference between fabrication and obsolescence?"

_CITED_ID_RE = re.compile(r"\[([a-z0-9][a-z0-9_-]{1,80})\]")


def ask_api() -> str:
    """The endpoint under test (``ASK_API``), or ``""`` when not set."""
    return os.environ.get("ASK_API", "").strip()


def ask(question: str, url: str | None = None, timeout: float = 90.0) -> str:
    """POST one question to the Ask endpoint and return the answer text.

    This is a paid call. Raises ``RuntimeError`` with a short reason when
    the endpoint cannot be reached or returns no answer.
    """
    import requests

    url = url or ask_api()
    if not url:
        raise RuntimeError("ASK_API is not set")
    if not url.startswith(("http://", "https://")):
        raise RuntimeError("ASK_API must be an http(s) URL")
    try:
        resp = requests.post(url, json={"question": question}, timeout=timeout)
        payload = resp.json()
    except (requests.RequestException, ValueError) as exc:
        raise RuntimeError(f"ask call failed: {type(exc).__name__}") from exc
    answer = (
        str(payload.get("answer") or "").strip() if isinstance(payload, dict) else ""
    )
    if not answer:
        raise RuntimeError(
            f"the endpoint returned no answer (status {resp.status_code})"
        )
    return answer


def invented_ids(answer: str, known_ids: frozenset[str] | set[str]) -> list[str]:
    """Bracketed ids in an answer that are no node of the KG.

    Ask cites tools, failure modes, papers, taxonomies, incidents and
    recipes, so ``known_ids`` must hold the ids of every kind.
    """
    return sorted(set(_CITED_ID_RE.findall(answer)) - set(known_ids))


def problems_scope_creep_answer(
    answer: str, tagged_tools: set[str], known_ids: set[str] | frozenset[str]
) -> list[str]:
    """The answer must name a tool the KG tags for scope_creep and cite
    nothing that is not in the KG."""
    problems = []
    low = answer.lower()
    if not any(tool_id in low for tool_id in tagged_tools):
        problems.append("names no tool that the catalog tags for scope_creep")
    bogus = invented_ids(answer, known_ids)
    if bogus:
        problems.append(f"cites ids that are not in the KG: {bogus}")
    return problems


def problems_two_modes_answer(
    answer: str, known_ids: set[str] | frozenset[str]
) -> list[str]:
    """The answer must speak of both modes and cite nothing invented."""
    problems = []
    low = answer.lower()
    for mode in ("fabrication", "obsolescence"):
        if mode not in low:
            problems.append(f"does not mention {mode}")
    bogus = invented_ids(answer, known_ids)
    if bogus:
        problems.append(f"cites ids that are not in the KG: {bogus}")
    return problems


def _kg_facts() -> tuple[set[str], frozenset[str]]:
    """(tools tagged for scope_creep, every node id) of the repository KG."""
    from pipeline import kg

    snapshot = kg.load()
    tagged = {
        tool_id
        for tool_id, tool in snapshot.tool_dicts().items()
        if "scope_creep" in tool["addresses_failure_modes"]
    }
    return tagged, snapshot.ids()


# promptfoo entry points (``file://evals/_assertions.py:<name>``). promptfoo
# has no "skipped" result, so a probe that cannot run fails with the reason.


def _grade(problems: list[str], ok: str) -> dict:
    if problems:
        return {"pass": False, "score": 0.0, "reason": "; ".join(problems)}
    return {"pass": True, "score": 1.0, "reason": ok}


def _run_probe(question: str, judge) -> dict:
    if not ask_api():
        return _grade(["NOT RUN: ASK_API is not set, so no model was asked"], "")
    try:
        answer = ask(question)
    except RuntimeError as exc:
        return _grade([str(exc)], "")
    return _grade(judge(answer), "answer checked against the KG")


def assert_ask_recommends_supervisor(
    output, context
):  # noqa: ARG001 - promptfoo signature
    tagged, known = _kg_facts()
    return _run_probe(
        SCOPE_CREEP_QUESTION, lambda a: problems_scope_creep_answer(a, tagged, known)
    )


def assert_ask_distinguishes_failure_modes(output, context):  # noqa: ARG001
    _, known = _kg_facts()
    return _run_probe(TWO_MODES_QUESTION, lambda a: problems_two_modes_answer(a, known))
