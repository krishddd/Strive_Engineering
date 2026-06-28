"""Self-consistency voting over multiple verdicts.

LLM-as-a-judge is unreliable: the same input judged twice can flip ("Rating
Roulette", arXiv:2510.27106), high test-retest reliability coexists with severe
bias ("Reliability without Validity", arXiv:2606.19544), and judges prefer their
own outputs (arXiv:2504.03846). The mitigation when a check is *not* deterministic
is to sample it several times independently and require a majority — and to
**escalate on disagreement** rather than trust a single judgment.

Where a deterministic check exists (SHA existence, diff integrity) prefer it
outright; this module is for the cases where judgment is unavoidable.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass
class ConsensusResult:
    decision: bool | None  # True/False if a majority agrees; None if escalate
    approve_votes: int
    reject_votes: int
    agreement: float  # share of votes for the winning side
    escalate: bool


def majority_vote(votes: list[bool], threshold: float = 0.66) -> ConsensusResult:
    """Aggregate boolean verdicts.

    ``decision`` is the majority side only if its share ``>= threshold``;
    otherwise the result is an escalation (``decision=None, escalate=True``).
    An empty vote set escalates — absence of evidence is not approval.
    """
    n = len(votes)
    if n == 0:
        return ConsensusResult(None, 0, 0, 0.0, True)

    approve = sum(1 for v in votes if v)
    reject = n - approve
    winning = max(approve, reject)
    agreement = winning / n

    if agreement < threshold:
        return ConsensusResult(None, approve, reject, agreement, True)

    return ConsensusResult(approve >= reject, approve, reject, agreement, False)
