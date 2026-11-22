"""The saica-supervise skill ships from two paths that must stay identical,
and both must be what the generator produces from the current repository.

``skills/saica-supervise/SKILL.md`` is the copy installed via the skills
lockfile / docs; ``plugin/skills/saica-supervise/SKILL.md`` is the copy the
Claude Code plugin (``.claude-plugin/marketplace.json`` -> ``./plugin``)
installs. Both are written by ``python -m validator.generate_skills``.

Comparing the two files with each other is not enough: from May to
November 2026 they were identical to each other and six months behind the
knowledge graph (review 2026-11-21, E11). So the test also renders the
skill in-process and compares. The rendering carries the date of
``data/MANIFEST.json``, not today's date, so no line needs masking and the
test gives the same answer on every day.
"""

from __future__ import annotations

from pathlib import Path

from validator.generate_skills import _render_plugin_skill, _render_text, build_payload

ROOT = Path(__file__).resolve().parents[1]
PUBLIC = ROOT / "skills" / "saica-supervise" / "SKILL.md"
PLUGIN = ROOT / "plugin" / "skills" / "saica-supervise" / "SKILL.md"
SKILLS_MD = ROOT / "SKILLS.md"

REGENERATE = "run `python -m validator.generate_skills` and commit all three files"


def _first_difference(expected: str, actual: str) -> str:
    for number, (want, got) in enumerate(
        zip(expected.splitlines(), actual.splitlines()), start=1
    ):
        if want != got:
            return (
                f"line {number}:\n  generator: {want[:160]}\n  file:      {got[:160]}"
            )
    return f"length differs: generator {len(expected)} chars, file {len(actual)} chars"


def test_saica_supervise_skill_copies_are_identical() -> None:
    assert (
        PUBLIC.read_bytes() == PLUGIN.read_bytes()
    ), f"{PUBLIC.relative_to(ROOT)} and {PLUGIN.relative_to(ROOT)} differ; {REGENERATE}"


def test_skill_copies_match_the_generator() -> None:
    expected = _render_plugin_skill(build_payload())
    for path in (PUBLIC, PLUGIN):
        actual = path.read_text(encoding="utf-8")
        assert actual == expected, (
            f"{path.relative_to(ROOT)} is not the generator's output; {REGENERATE}.\n"
            + _first_difference(expected, actual)
        )


def test_skills_md_matches_the_generator() -> None:
    expected = _render_text(build_payload())
    actual = SKILLS_MD.read_text(encoding="utf-8")
    assert (
        actual == expected
    ), f"SKILLS.md is not the generator's output; {REGENERATE}.\n" + _first_difference(
        expected, actual
    )
