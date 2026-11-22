"""The nine shipped reviewer prompts are the benchmark's prompts (review issue I8, evidence KT-12).

For every mode: the template in site/public/kit/prompts/<mode>.md, filled by the kit's reviewer, gives exactly
the text the benchmark's own constant gives with the same values; the reviewer finds the right verdict field;
and the prompt file names the placeholders the benchmark filled.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
KIT = REPO / "site" / "public" / "kit"


def _load(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, str(path))
    mod = importlib.util.module_from_spec(spec)
    prev, sys.dont_write_bytecode = sys.dont_write_bytecode, True
    try:
        spec.loader.exec_module(mod)
    finally:
        sys.dont_write_bytecode = prev
    return mod


rv = _load("saica_llm_review_prompts", KIT / "saica_llm_review.py")
gen = _load("saica_kit_gen_prompts", REPO / "bench" / "kitbuilder" / "gen" / "gen.py")
MODES = list(gen.SPEC)


def template_of(mode: str) -> str:
    text = (KIT / "prompts" / (gen.FM_FILE.get(mode, mode) + ".md")).read_text()
    block = rv.first_fenced_block(text)
    assert block is not None, mode
    return block


def test_there_are_nine_prompt_files_and_one_rule_file():
    names = sorted(p.name for p in (KIT / "prompts").glob("*.md"))
    assert names == sorted(gen.FM_FILE.get(m, m) + ".md" for m in MODES)
    assert len(names) == 9
    others = sorted(p.name for p in (KIT / "prompts").glob("*") if p.suffix != ".md")
    assert others == ["test_manipulation.rule.txt"]


def test_rule_file_is_the_benchmark_rule():
    """The {rule} text of the test-manipulation prompt, as the benchmark filled it in."""
    rule = gen.const("test_manipulation/run_tools.py", "RULE")
    assert (KIT / "prompts" / "test_manipulation.rule.txt").read_text() == rule.rstrip(
        "\n"
    ) + "\n"


@pytest.mark.parametrize("mode", MODES)
def test_shipped_prompt_equals_the_benchmark_constant(mode):
    sp = gen.SPEC[mode]
    constant = gen.const(
        f"{sp['dir']}/run_tools.py", sp["const"]
    )  # read with ast from the run script
    names = gen.placeholders(constant)
    # values with braces and quotes: nothing may be substituted twice or escaped
    values = {n: 'VALUE<%s> {not_a_placeholder} {{x}} "q"\n' % n for n in names}
    want = constant.format(**values)
    got, unknown = rv.fill_template(template_of(mode), values)
    assert unknown == []
    assert got == want
    assert rv.placeholder_names(template_of(mode)) == list(dict.fromkeys(names))


@pytest.mark.parametrize("mode", MODES)
def test_reviewer_finds_the_verdict_field_of_each_prompt(mode):
    key = gen.SPEC[mode]["key"]
    template = template_of(mode)
    assert rv.detect_flag_field(template) == key
    answer = 'Reasoning...\n```json\n{"%s": true, "evidence": "e"}\n```' % key
    obj, field = rv.find_verdict(answer, key)
    assert rv.judge(obj, field, answer, "stop")[0] == "flagged"


@pytest.mark.parametrize("mode", MODES)
def test_placeholders_the_kit_cannot_fill_by_itself_are_named_in_the_builder_data(mode):
    """A prompt that needs more than the task and the diff must come with --fill options in the generated entry."""
    import json

    names = set(rv.placeholder_names(template_of(mode))) - set(rv.BUILTIN_KEYS)
    kit = json.loads((REPO / "site" / "public" / "bench" / "kit.json").read_text())
    m = next(x for x in kit["modes"] if x["id"] == mode)
    commands = [
        r["kit_check"]["entry"]["command"]
        for r in m["rows"]
        if r.get("kit_check") and r["category"] == "llm"
    ]
    assert commands, mode
    for cmd in commands:
        for name in names:
            assert f"--fill {name}=" in cmd, (mode, name)
