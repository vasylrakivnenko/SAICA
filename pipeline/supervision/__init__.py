"""Supervision package — prevention-event logging and CLI shims.

This package is the home of SAICA-KG's first-party *prevention* layer.
The KG entries that motivated it:

- ``data/failure_modes/scope_creep.yml`` — the FM the project's CLAUDE.md
  guards against (plan-first, scope-respecting working agreement).
- ``data/failure_modes/security_vulnerability.yml`` — pre-commit hooks like
  ``detect-private-key`` and ``semgrep`` block insecure code from landing.
- ``data/tools/semgrep.yml`` — wired as a pre-commit hook; logs denials
  through :func:`pipeline.supervision.logger.log_prevention`.
- ``data/tools/dependabot.yml`` — sibling supervisor (citation-style guide
  for the per-file headers in this package).

The package is stdlib-only so it can be imported anywhere in the repo
without dragging in heavy dependencies.
"""

from pipeline.supervision.logger import (
    LOG_DIR_DEFAULT,
    log_prevention,
    read_events,
)

__all__ = ["LOG_DIR_DEFAULT", "log_prevention", "read_events"]
