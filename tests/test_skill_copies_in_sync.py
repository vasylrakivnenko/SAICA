"""The saica-supervise skill ships from two paths that must stay identical.

``skills/saica-supervise/SKILL.md`` is the copy installed via the skills
lockfile / docs; ``plugin/skills/saica-supervise/SKILL.md`` is the copy the
Claude Code plugin (``.claude-plugin/marketplace.json`` -> ``./plugin``)
installs. Nothing else keeps them in sync, so an edit to one silently forks
the published guidance.
"""

from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_saica_supervise_skill_copies_are_identical() -> None:
    a = ROOT / "skills" / "saica-supervise" / "SKILL.md"
    b = ROOT / "plugin" / "skills" / "saica-supervise" / "SKILL.md"
    assert a.read_bytes() == b.read_bytes(), (
        f"{a.relative_to(ROOT)} and {b.relative_to(ROOT)} differ; "
        "copy the edited one over the other"
    )
