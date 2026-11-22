"""Cost caps for paid API calls.

A :class:`CallBudget` is threaded through callers that talk to a paid
model or search API. The protocol has two steps, so that a call is counted
**before** it is paid for:

1. ``budget.reserve()`` before the request is sent. It raises
   :class:`CostCapExceeded` when a ceiling is already reached; the refused
   call is not counted and nothing is spent.
2. ``budget.record(tokens=...)`` after the response, with the tokens the
   provider reported. It never raises: the money is spent and the caller
   should keep the answer. The next ``reserve()`` sees the new total.

``budget.release()`` gives back a reserved call that was never sent (for
example when a step before the request failed).

:class:`DailyBudget` is the same thing with counters that start again at
midnight UTC; the web service uses it.

``consume()`` is the older single-step method. It counts a call after the
fact and raises once the ceiling is passed, so one call beyond the cap is
always paid for. The ingestion modules still call it; new code should not.

The budget is intentionally dumb. It does not know dollar-per-token
pricing. CLI entry points catch :class:`CostCapExceeded` and exit with
code ``3``.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime, timezone
from threading import Lock
from typing import Callable, Optional


class CostCapExceeded(RuntimeError):
    """Raised when a :class:`CallBudget` ceiling has been hit."""


@dataclass
class CallBudget:
    """Caps on calls and tokens for one run of a program.

    ``max_calls`` caps the number of calls. ``max_tokens_estimate`` caps a
    running total of reported tokens: once it is reached, no further call
    is reserved. ``None`` means "no cap on this axis". Safe to share
    between threads.
    """

    max_calls: Optional[int] = None
    max_tokens_estimate: Optional[int] = None
    _calls_made: int = 0
    _tokens_used: int = 0
    _lock: Lock = field(default_factory=Lock, repr=False, compare=False)

    # -- two-step protocol ---------------------------------------------------

    def reserve(self) -> None:
        """Count one call that is about to be made.

        Raises :class:`CostCapExceeded` when the call cap or the token cap
        is already reached. A refused call is not counted.
        """
        with self._lock:
            if self.max_calls is not None and self._calls_made >= self.max_calls:
                raise CostCapExceeded(f"max_calls={self.max_calls} reached")
            if (
                self.max_tokens_estimate is not None
                and self._tokens_used >= self.max_tokens_estimate
            ):
                raise CostCapExceeded(
                    f"max_tokens_estimate={self.max_tokens_estimate} reached"
                )
            self._calls_made += 1

    def release(self) -> None:
        """Give back one reserved call that was never sent."""
        with self._lock:
            self._calls_made = max(0, self._calls_made - 1)

    def record(self, *, tokens: int = 0) -> None:
        """Add the tokens a finished call reported. Never raises."""
        with self._lock:
            self._tokens_used += max(0, int(tokens))

    # -- older single-step method --------------------------------------------

    def consume(self, *, call: bool = True, tokens: int = 0) -> None:
        """Record a call and/or tokens after the fact; raise if past a ceiling.

        Kept for the ingestion modules. It raises AFTER counting, so the
        call that trips the cap has already been paid for. Prefer
        :meth:`reserve` and :meth:`record`.
        """
        with self._lock:
            if call:
                self._calls_made += 1
            self._tokens_used += max(0, int(tokens))
            calls, used = self._calls_made, self._tokens_used
        if self.max_calls is not None and calls > self.max_calls:
            raise CostCapExceeded(
                f"max_calls={self.max_calls} exceeded after {calls} calls"
            )
        if self.max_tokens_estimate is not None and used > self.max_tokens_estimate:
            raise CostCapExceeded(
                f"max_tokens_estimate={self.max_tokens_estimate} exceeded after "
                f"{used} tokens"
            )

    def summary(self) -> str:
        """One-line tally for logs (shown on budget-hit exit)."""
        return f"calls={self._calls_made} tokens≈{self._tokens_used}"


def _utc_today() -> date:
    return datetime.now(timezone.utc).date()


@dataclass
class DailyBudget(CallBudget):
    """A :class:`CallBudget` whose counters start again each UTC day.

    The counters live in this process. Two instances of a service each
    have their own, so the real daily ceiling of a deployment is this cap
    times the number of instances that ran that day.
    """

    today: Callable[[], date] = field(default=_utc_today, repr=False, compare=False)
    _day: Optional[date] = field(default=None, repr=False, compare=False)

    def _roll(self) -> None:
        now = self.today()
        with self._lock:
            if self._day != now:
                self._day = now
                self._calls_made = 0
                self._tokens_used = 0

    def reserve(self) -> None:
        self._roll()
        super().reserve()

    def release(self) -> None:
        self._roll()
        super().release()

    def record(self, *, tokens: int = 0) -> None:
        self._roll()
        super().record(tokens=tokens)

    def consume(self, *, call: bool = True, tokens: int = 0) -> None:
        self._roll()
        super().consume(call=call, tokens=tokens)

    def summary(self) -> str:
        self._roll()
        return super().summary()


__all__ = ["CallBudget", "CostCapExceeded", "DailyBudget"]
