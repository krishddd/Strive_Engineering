"""Grounded verifier — the front door to loopguard's verification core.

A loop's claim of "done" (or here, "this triage is accurate") is only trustworthy
if it is falsifiable by an external check the loop cannot game. This module turns
a set of cited commit SHAs into a pass/fail verdict, and crucially distinguishes
*fabricated* (a cited SHA does not exist → the run is invalid) from *unverifiable*
(the verifier could not run → escalate, never silently pass).
"""

from __future__ import annotations

from dataclasses import dataclass

from .core import Loopguard


class VerificationError(RuntimeError):
    """The verifier itself could not run; the caller must escalate, not pass."""


@dataclass
class VerificationResult:
    valid: bool
    grounded: list[str]
    fabricated: list[str]


class Verifier:
    def __init__(self, guard: Loopguard | None = None) -> None:
        self.guard = guard or Loopguard()

    def verify_commit_claims(self, repo: str, shas: list[str]) -> VerificationResult:
        data = self.guard.verify_shas(repo, shas)
        if data.get("unverifiable"):
            raise VerificationError(
                f"could not verify SHAs against {repo!r} — escalate (do not treat as clean)"
            )
        grounded, fabricated = [], []
        for claim in data.get("claims", []):
            verdict = claim.get("verdict")
            # loopguard emits a tagged enum: {"verdict": "grounded"} (or
            # {"verdict": "fabricated", "detail": ...}). Unwrap the tag.
            tag = verdict.get("verdict") if isinstance(verdict, dict) else verdict
            if tag == "grounded":
                grounded.append(claim["sha"])
            else:
                fabricated.append(claim["sha"])
        return VerificationResult(
            valid=bool(data.get("valid")) and not fabricated,
            grounded=grounded,
            fabricated=fabricated,
        )
