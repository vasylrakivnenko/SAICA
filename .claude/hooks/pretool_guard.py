#!/usr/bin/env python3
"""Claude Code PreToolUse hook for this repository. Opt-in; off by default.

What it does (logic and tests: pipeline/supervision/pretool.py):
  * denies a Bash command that skips commit hooks (--no-verify, git commit -n);
  * asks before an Edit / Write under a path CLAUDE.md lists as off-limits;
  * appends each of its own decisions to .saica/prevention_log/ with
    recorded_by "hook".

To enable it, copy the "hooks" block of .claude/hooks/settings.example.json
into your own .claude/settings.local.json. Nothing here enables it for you.

Standard library only. On any internal error it prints nothing and exits 0,
so Claude Code's normal permission flow applies.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

try:
    from pipeline.supervision.pretool import main
except Exception:  # noqa: BLE001 - a broken checkout must not block tool calls
    sys.exit(0)

sys.exit(main())
