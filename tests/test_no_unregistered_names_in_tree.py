"""K9 (review 2026-11-21): no file in the repository may point at the
unregistered domain or the GitHub organisation that does not exist.

The project's site is ``saica.ai`` and the repository is
``github.com/vasylrakivnenko/SAICA``. Whoever registers one of the two old
names would receive every link that still points there.

``tests/test_no_unregistered_domain.py`` checks the schema / validator paths
in detail. This test is the wide net: every file git knows about (tracked,
or new and not ignored), with a short list of files that may name the old
strings because they report or test for them.
"""

from __future__ import annotations

import re
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]

# Built from pieces so that this file does not contain the names itself.
_DOMAIN = "saica-kg" + r"\.dev"
_ORG = r"github\.com/" + "saica-kg" + r"(?![\w-])"
OLD_NAMES = re.compile(f"{_DOMAIN}|{_ORG}")

# Files that may contain the old names.
ALLOWED_PREFIXES = (
    # the review that found the problem, and the notes of the fix rounds
    "REWIEW_NOV_21.md",
    "FIXES_NOV_21.md",
    "research/review_20261121/",
    "research/review_20261121_r2/",
    "research/fixes_20261121/",
    # a research note that reports the same problem
    "research/seo_20261121/content_plan.md",
    # retracted records are kept as they were
    "archive/",
)
ALLOWED_FILES = {
    # tests that name the strings in order to reject them
    "tests/test_no_unregistered_domain.py",
    "pipeline/audit/tests/test_audit_cases.py",
}


def _git_files() -> list[str]:
    try:
        out = subprocess.run(
            ["git", "ls-files", "-z", "--cached", "--others", "--exclude-standard"],
            cwd=ROOT,
            capture_output=True,
            check=True,
        ).stdout
    except (OSError, subprocess.CalledProcessError):
        pytest.skip("not a git checkout (or git is not installed)")
    return sorted(p for p in out.decode("utf-8", "replace").split("\0") if p)


def _allowed(path: str) -> bool:
    return path in ALLOWED_FILES or path.startswith(ALLOWED_PREFIXES)


def test_no_file_names_the_unregistered_domain_or_organisation() -> None:
    files = _git_files()
    assert len(files) > 500, "git listed too few files; is this the repository root?"
    hits: list[str] = []
    for rel in files:
        if _allowed(rel):
            continue
        path = ROOT / rel
        if not path.is_file() or path.stat().st_size > 20_000_000:
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except (UnicodeDecodeError, OSError):
            continue  # binary, or removed since git listed it
        if not OLD_NAMES.search(text):
            continue
        for number, line in enumerate(text.splitlines(), start=1):
            if OLD_NAMES.search(line):
                hits.append(f"{rel}:{number}: {line.strip()[:120]}")
    assert not hits, (
        "unregistered domain or organisation name found; use saica.ai or"
        " github.com/vasylrakivnenko/SAICA:\n  " + "\n  ".join(hits)
    )


def test_the_pattern_catches_the_old_names_and_nothing_else() -> None:
    assert OLD_NAMES.search("see https://" + "saica-kg" + ".dev/assess")
    assert OLD_NAMES.search("(https://github.com/" + "saica-kg" + "/saica-kg)")
    assert not OLD_NAMES.search("https://github.com/saica-kg-fork/x")
    assert not OLD_NAMES.search("https://saica.ai/tools/")
    assert not OLD_NAMES.search("/plugin install saica-supervise@saica-kg")


def test_this_file_is_not_an_exception_for_itself() -> None:
    assert not OLD_NAMES.search(Path(__file__).read_text(encoding="utf-8"))
