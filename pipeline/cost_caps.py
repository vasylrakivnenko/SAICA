"""Per-run cost caps for paid API calls.

A :class:`CallBudget` is threaded through callers that talk to Kimi,
Perplexity, or Cohere. Each HTTP call calls ``budget.consume(...)``; when
the configured ceiling is exceeded, :class:`CostCapExceeded` is raised.
CLI entry points catch it and exit with code ``3`` (reserved for
"budget hit" — distinct from other error classes).

The budget is intentionally dumb. It does not know dollar-per-token
pricing; the CLI defaults are tuned to keep a stray ``--limit 10000`` or
infinite loop from costing more than a few tens of cents on any one
backend (20 Kimi calls ~= $0.10, etc.). If a caller wants finer control
they pass a non-default ``--max-calls`` / ``--max-cost-tokens``.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional


class CostCapExceeded(RuntimeError):
    """Raised when a :class:`CallBudget` ceiling has been hit."""


@dataclass
class CallBudget:
    """Soft + hard caps on calls/tokens for one CLI invocation.

    ``max_calls`` is a hard cap on the number of HTTP calls. ``max_tokens_estimate``
    is a soft running tally of ``usage.total_tokens`` (or a caller-supplied
    estimate); when either is exceeded the next :meth:`consume` raises
    :class:`CostCapExceeded`.

    Both ceilings are optional — ``None`` means "no cap on this axis".
    """

    max_calls: Optional[int] = None
    max_tokens_estimate: Optional[int] = None
    _calls_made: int = 0
    _tokens_used: int = 0

    def consume(self, *, call: bool = True, tokens: int = 0) -> None:
        """Record one call and/or a token delta; raise if past a ceiling.

        Raising AFTER incrementing means the summary reflects the call
        that tripped the cap. That's intentional so the CLI can log an
        accurate total.
        """
        if call:
            self._calls_made += 1
        self._tokens_used += max(0, int(tokens))
        if self.max_calls is not None and self._calls_made > self.max_calls:
            raise CostCapExceeded(
                f"max_calls={self.max_calls} exceeded after {self._calls_made} calls"
            )
        if (
            self.max_tokens_estimate is not None
            and self._tokens_used > self.max_tokens_estimate
        ):
            raise CostCapExceeded(
                f"max_tokens_estimate={self.max_tokens_estimate} exceeded after "
                f"{self._tokens_used} tokens"
            )

    def summary(self) -> str:
        """One-line human-readable tally (shown on budget-hit exit)."""
        return f"calls={self._calls_made} tokens≈{self._tokens_used}"


__all__ = ["CallBudget", "CostCapExceeded"]
