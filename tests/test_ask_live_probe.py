"""Live probes of the Ask endpoint, and tests of the probes themselves.

The two live tests ask a real model through ``ASK_API`` and cost money.
Without ``ASK_API`` they are **skipped** and pytest says so; they never
count as passed (review H7: the promptfoo versions reported PASS when
nothing had run). The other tests need no network.
"""

from __future__ import annotations

import pytest

from evals import _assertions as probes
from pipeline import kg

needs_endpoint = pytest.mark.skipif(
    not probes.ask_api(), reason="ASK_API is not set: no model was asked"
)

KNOWN = {"litellm", "scope_creep", "fabrication", "obsolescence", "some-paper-2025"}


def test_invented_ids_counts_every_kind_of_node_as_known() -> None:
    answer = (
        "Use [litellm] for [scope_creep], see [some-paper-2025] and [made-up-tool]."
    )
    assert probes.invented_ids(answer, KNOWN) == ["made-up-tool"]
    assert probes.invented_ids("No citations here.", KNOWN) == []


def test_scope_creep_judge_wants_a_tagged_tool_and_no_invented_id() -> None:
    good = (
        "LiteLLM [litellm] can cap what an agent may call, which limits [scope_creep]."
    )
    assert probes.problems_scope_creep_answer(good, {"litellm"}, KNOWN) == []
    assert probes.problems_scope_creep_answer("Try harder.", {"litellm"}, KNOWN) == [
        "names no tool that the catalog tags for scope_creep"
    ]
    assert probes.problems_scope_creep_answer(
        good + " Also [ghost].", {"litellm"}, KNOWN
    ) == ["cites ids that are not in the KG: ['ghost']"]


def test_two_modes_judge_wants_both_modes() -> None:
    assert (
        probes.problems_two_modes_answer(
            "[fabrication] invents, [obsolescence] is stale.", KNOWN
        )
        == []
    )
    assert probes.problems_two_modes_answer("Fabrication invents things.", KNOWN) == [
        "does not mention obsolescence"
    ]


def test_promptfoo_wrapper_fails_instead_of_passing_when_not_run(monkeypatch) -> None:
    monkeypatch.delenv("ASK_API", raising=False)
    for wrapper in (
        probes.assert_ask_recommends_supervisor,
        probes.assert_ask_distinguishes_failure_modes,
    ):
        result = wrapper("ignored", None)
        assert result["pass"] is False
        assert result["reason"].startswith("NOT RUN")


def test_promptfoo_wrapper_judges_a_stubbed_answer(monkeypatch) -> None:
    monkeypatch.setenv("ASK_API", "http://stub.invalid/api/ask")
    monkeypatch.setattr(probes, "_kg_facts", lambda: ({"litellm"}, frozenset(KNOWN)))
    monkeypatch.setattr(probes, "ask", lambda question: "Use [litellm].")
    assert probes.assert_ask_recommends_supervisor("ignored", None)["pass"] is True
    assert (
        probes.assert_ask_distinguishes_failure_modes("ignored", None)["pass"] is False
    )

    def unreachable(question):
        raise RuntimeError("ask call failed: URLError")

    monkeypatch.setattr(probes, "ask", unreachable)
    result = probes.assert_ask_recommends_supervisor("ignored", None)
    assert result == {
        "pass": False,
        "score": 0.0,
        "reason": "ask call failed: URLError",
    }


@needs_endpoint
def test_live_ask_names_a_tool_tagged_for_scope_creep() -> (
    None
):  # pragma: no cover - paid
    tagged, known = probes._kg_facts()
    answer = probes.ask(probes.SCOPE_CREEP_QUESTION)
    assert probes.problems_scope_creep_answer(answer, tagged, known) == [], answer[:400]


@needs_endpoint
def test_live_ask_tells_fabrication_from_obsolescence() -> (
    None
):  # pragma: no cover - paid
    answer = probes.ask(probes.TWO_MODES_QUESTION)
    assert probes.problems_two_modes_answer(answer, kg.load().ids()) == [], answer[:400]
