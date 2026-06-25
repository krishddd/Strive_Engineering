"""The loop runtime — trigger -> gather -> verify -> state -> escalate.

A loop is described by a JSON spec (see ``schemas/loop.schema.json``). The runtime
supplies the four things that make a loop more than a cron job:

* **trigger / iteration control** with hard brakes (Budget/Ledger),
* a **grounded verifier** every claim must pass (delegated to the Rust core),
* **external state** (read the cursor, write outcomes, append the run log),
* a **stop/escalate** rule that distinguishes fatal from recoverable errors.

The first supported loop kind, ``git-commit-triage``, is fully deterministic: it
classifies new commits by a transparent heuristic and cites each one's SHA. The
value on display is the *machinery* — an LLM-driven loop swaps the classify step
for an agent call while keeping the same guard/verify/state/escalate spine.
"""

from __future__ import annotations

import datetime as _dt
from dataclasses import dataclass, field
from typing import Any

from .budget import Budget, BudgetExceeded, Ledger
from .core import Loopguard
from .gitscan import Commit, GitError, ahead_behind, commits, is_git_repo, resolve
from .state import StateStore
from .verifier import VerificationError, Verifier


def _utc_now() -> str:
    return _dt.datetime.now(_dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


HIGH_KEYWORDS = ("fix", "security", "vuln", "cve", "bug", "hotfix", "revert", "incident")
NOISE_PREFIXES = ("merge ", "merge pull request", "rustfmt", "clippy", "chore(fmt)")


@dataclass
class Finding:
    bucket: str  # "high" | "watch" | "noise"
    text: str
    sha: str  # short sha — the groundable citation


@dataclass
class RunResult:
    result: str  # clean | found | error | escalated
    findings: list[Finding] = field(default_factory=list)
    note: str = ""
    cursors: dict[str, str] = field(default_factory=dict)


def classify(commit: Commit) -> str:
    subject = commit.subject.lower()
    if any(subject.startswith(p) for p in NOISE_PREFIXES):
        return "noise"
    if any(k in subject for k in HIGH_KEYWORDS):
        return "high"
    return "watch"


class LoopRuntime:
    """Runs one loop spec for one cycle."""

    def __init__(
        self,
        spec: dict[str, Any],
        state: StateStore,
        guard: Loopguard | None = None,
    ) -> None:
        self.spec = spec
        self.state = state
        self.loop_id = spec["id"]
        self.guard = guard or Loopguard()
        self.verifier = Verifier(self.guard)
        b = spec.get("budget", {})
        self.ledger = Ledger(
            Budget(
                max_tokens=b.get("max_tokens"),
                max_iterations=b.get("max_iterations", 1),
                wall_clock_secs=b.get("wall_clock_secs"),
            )
        )

    # -- the cycle ----------------------------------------------------------

    def run(self) -> RunResult:
        kind = self.spec.get("kind")
        if kind != "git-commit-triage":
            raise ValueError(f"unsupported loop kind: {kind!r}")

        # Kill switch first.
        if self.spec.get("paused"):
            return self._finish(RunResult("clean", note="paused"))

        try:
            self.ledger.tick()  # single pass; a second tick would raise
        except BudgetExceeded as e:
            return self._finish(RunResult("escalated", note=str(e)))

        target = self.spec["target"]["repo"]
        refs = self.spec["target"]["refs"]
        first_since = self.spec["target"].get("first_run_since", "7 days ago")

        # Fatal vs recoverable: an unreadable target is fatal -> escalate, never retry.
        if not is_git_repo(target):
            return self._finish(
                RunResult("escalated", note=f"target not a readable git repo: {target}")
            )

        prior = self.state.read_section(self.loop_id)
        prior_cursors: dict[str, str] = prior.get("cursors", {})

        findings: list[Finding] = []
        new_cursors: dict[str, str] = {}
        seen: set[str] = set()  # dedupe commits shared across refs
        try:
            for ref in refs:
                head = resolve(target, ref)
                new_cursors[ref] = head
                for c in commits(target, ref, prior_cursors.get(ref), first_since):
                    if c.sha in seen:
                        continue
                    seen.add(c.sha)
                    findings.append(Finding(classify(c), c.subject, c.short))
            # Branch divergence signal (ahead/behind) when >1 ref is watched.
            if len(refs) >= 2:
                ahead, _ = ahead_behind(target, refs[-1], refs[0])
                if ahead:
                    tip = resolve(target, refs[0])
                    findings.append(
                        Finding("high", f"{refs[0]} is {ahead} commits ahead of {refs[-1]}", tip[:7])
                    )
        except GitError as e:
            return self._finish(RunResult("escalated", note=f"git error (fatal): {e}"))

        # Empty run: no new commits anywhere. Do NOT invent findings.
        actionable = [f for f in findings if f.bucket in ("high", "watch")]
        if not actionable:
            return self._finish(
                RunResult("clean", note="no new commits since cursors", cursors=new_cursors)
            )

        # Grounded verification — the whole game. Every cited SHA must resolve.
        cited = [f.sha for f in actionable]
        try:
            verdict = self.verifier.verify_commit_claims(target, cited)
        except VerificationError as e:
            return self._finish(RunResult("escalated", note=str(e)))
        if not verdict.valid:
            return self._finish(
                RunResult(
                    "error",
                    note=f"invalid run: fabricated SHAs {verdict.fabricated}",
                    cursors=prior_cursors,  # do NOT advance cursors on an invalid run
                )
            )

        return self._finish(RunResult("found", findings=findings, cursors=new_cursors))

    # -- persistence --------------------------------------------------------

    def _finish(self, res: RunResult) -> RunResult:
        ts = _utc_now()
        section = {
            "phase": self.spec.get("phase", "L1"),
            "last_run": ts,
            "last_result": res.result,
            "cursors": res.cursors or self.state.read_section(self.loop_id).get("cursors", {}),
            "findings": [f.__dict__ for f in res.findings],
            "note": res.note,
            "tokens_spent": self.ledger.tokens_spent,
        }
        # Writing state is a guarded action too (defense in depth is conceptual
        # here; the file write is local and non-destructive).
        self.state.write_section(self.loop_id, section)
        self.state.append_runlog(
            {
                "ts": ts,
                "loop": self.loop_id,
                "result": res.result,
                "action": "wrote-state" if res.result != "escalated" else "escalated-to-human",
                "high": sum(1 for f in res.findings if f.bucket == "high"),
                "watch": sum(1 for f in res.findings if f.bucket == "watch"),
                "note": res.note,
            }
        )
        return res
