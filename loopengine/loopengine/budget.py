"""Python-side budget ledger (mirrors the Rust ``budget`` module).

The runtime tracks spend here for fast in-process decisions; the Rust core owns
the authoritative cap semantics. Both refuse to exceed a cap rather than warn —
the brake is structural.
"""

from __future__ import annotations

import time
from dataclasses import dataclass


class BudgetExceeded(RuntimeError):
    """Raised when a run would breach a cap. Carries which axis tripped."""

    def __init__(self, axis: str, detail: str) -> None:
        super().__init__(f"budget exceeded ({axis}): {detail}")
        self.axis = axis


@dataclass
class Budget:
    max_tokens: int | None = None
    max_iterations: int | None = None
    wall_clock_secs: int | None = None


class Ledger:
    """Tracks spend against a Budget for one run (trajectory)."""

    def __init__(self, budget: Budget) -> None:
        self.budget = budget
        self.tokens_spent = 0
        self.iterations = 0
        self._start = time.monotonic()

    def spend(self, tokens: int) -> None:
        if self.budget.max_tokens is not None and self.tokens_spent + tokens > self.budget.max_tokens:
            raise BudgetExceeded("tokens", f"{self.tokens_spent}+{tokens} > {self.budget.max_tokens}")
        self.tokens_spent += tokens

    def tick(self) -> None:
        if self.budget.max_iterations is not None and self.iterations + 1 > self.budget.max_iterations:
            raise BudgetExceeded("iterations", f"cap {self.budget.max_iterations} reached")
        self.iterations += 1

    def check_wall_clock(self) -> None:
        if self.budget.wall_clock_secs is not None:
            elapsed = time.monotonic() - self._start
            if elapsed > self.budget.wall_clock_secs:
                raise BudgetExceeded("wall_clock", f"{elapsed:.0f}s > {self.budget.wall_clock_secs}s")

    @property
    def elapsed_secs(self) -> float:
        return time.monotonic() - self._start
