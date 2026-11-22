"""Prevention log and the PreToolUse guard.

Two parts:

* :mod:`pipeline.supervision.pretool` — the logic of
  ``.claude/hooks/pretool_guard.py``, a Claude Code ``PreToolUse`` hook that
  decides by itself: it denies a Bash command that skips commit hooks
  (``--no-verify``) and asks before an edit under the paths ``CLAUDE.md``
  lists as off-limits. It is opt-in: nothing runs until the owner adds it
  to their own settings (``.claude/hooks/settings.example.json``).
* :mod:`pipeline.supervision.logger` — the JSONL log. Every line says who
  wrote it (``recorded_by``): the hook itself, or someone at the command
  line. Only hook lines are observations.

Standard library only.
"""

from pipeline.supervision.logger import (
    LOG_DIR_DEFAULT,
    log_prevention,
    observed_events,
    read_events,
)

__all__ = ["LOG_DIR_DEFAULT", "log_prevention", "observed_events", "read_events"]
