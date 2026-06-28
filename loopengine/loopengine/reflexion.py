"""Evaluator-optimizer loop with Reflexion-style memory.

Blind retry oscillates (fix A breaks test B, fix B breaks test A). Reflexion
(Shinn et al., NeurIPS 2023, arXiv:2303.11366) and Self-Refine (arXiv:2303.17651)
fix this by feeding the *reason* a prior attempt failed back into the next one:
on REJECT the checker's feedback is distilled into a written reflection, appended
to an episodic memory, and handed to the maker for the next attempt — all bounded
by a hard iteration cap so it can never run away.

The maker and checker are injected callables, so this controller is pure and
deterministically testable. In production the maker is an LLM/agent step and the
checker combines deterministic checks (diff integrity, SHA grounding) with a
consistency-voted judgment; here those are just functions.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable, Protocol


class Maker(Protocol):
    def __call__(self, task: str, reflections: list[str]) -> str:
        """Produce a candidate solution given the task and prior reflections."""
        ...


@dataclass
class Critique:
    accepted: bool
    feedback: str  # why it failed (becomes the next reflection) or why it passed


# A checker takes the task and a candidate and returns a Critique.
Checker = Callable[[str, str], Critique]


@dataclass
class ReflexionResult:
    success: bool
    attempts: int
    solution: str | None
    reflections: list[str] = field(default_factory=list)
    escalated: bool = False
    note: str = ""


def run_reflexion(
    task: str,
    maker: Maker,
    checker: Checker,
    max_attempts: int = 3,
) -> ReflexionResult:
    """Maker → checker → reflect → retry, bounded by ``max_attempts``.

    Stops on the first accepted candidate. If the cap is reached without
    acceptance it escalates (it does NOT return the last unverified attempt as if
    it were done — that would be the premature-completion failure mode).
    """
    if max_attempts < 1:
        raise ValueError("max_attempts must be >= 1")

    reflections: list[str] = []
    for attempt in range(1, max_attempts + 1):
        candidate = maker(task, reflections)
        critique = checker(task, candidate)
        if critique.accepted:
            return ReflexionResult(
                success=True,
                attempts=attempt,
                solution=candidate,
                reflections=reflections,
                note="accepted by checker",
            )
        # Reflexion step: record *why* it failed for the next attempt.
        reflections.append(f"attempt {attempt}: {critique.feedback}")

    return ReflexionResult(
        success=False,
        attempts=max_attempts,
        solution=None,
        reflections=reflections,
        escalated=True,
        note=f"no accepted solution in {max_attempts} attempts — escalating to human",
    )
