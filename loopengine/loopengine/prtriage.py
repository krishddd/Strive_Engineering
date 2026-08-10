"""``pr-triage`` — a read-only L1 loop over open pull requests.

The commit-triage loop watches a repo's *commits*; this one watches its open
*pull requests*, through the same discipline: read-only, cursor-gated, and every
tool return injection-scanned before the loop acts on it (the ``GuardedConnector``
around a structurally read-only ``GitHubTransport``).

Grounding note — honestly stated. Commit-triage cites SHAs that ``loopguard``
resolves against the local repo, an ungameable external check. A PR lives on the
remote, so there is no local SHA to resolve; the grounding here is different but
still external: every finding cites a PR **number that came back from the GitHub
API** (not invented by any model — this loop is deterministic, no LLM), and that
payload already passed the injection gate. It stays L1 (report-only) precisely
because its verifier is weaker than commit-triage's.

Cursor discipline mirrors commit-triage: the loop remembers the newest
``updated_at`` it has seen and only reports PRs updated since — so a quiet day is
a *clean* run, not a re-report of every open PR.
"""

from __future__ import annotations

import datetime as _dt
import json
from typing import Any

from .budget import Budget, BudgetExceeded, Ledger
from .connectors import ConnectorError, GuardedConnector
from .runtime import Finding, RunResult

HIGH_KEYWORDS = ("fix", "security", "vuln", "cve", "hotfix", "revert", "incident")


def _utc_now() -> str:
    return _dt.datetime.now(_dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def classify_pr(pr: dict[str, Any]) -> str:
    """Bucket one trimmed PR. Drafts are noise; bot ``loop/*`` proposals and
    fix/security PRs are high; everything else open is watch."""
    if pr.get("draft"):
        return "noise"
    head = (pr.get("head") or "")
    title = (pr.get("title") or "").lower()
    if head.startswith("loop/"):
        return "high"  # a loop's own proposal, waiting on a human
    if any(k in title for k in HIGH_KEYWORDS):
        return "high"
    return "watch"


class PRTriageLoop:
    """Runs one ``pr-triage`` cycle against an injected, guarded connector."""

    def __init__(self, spec: dict[str, Any], state, connector: GuardedConnector) -> None:
        self.spec = spec
        self.state = state
        self.loop_id = spec["id"]
        self.connector = connector
        b = spec.get("budget", {})
        self.ledger = Ledger(
            Budget(
                max_tokens=b.get("max_tokens"),
                max_iterations=b.get("max_iterations", 1),
                wall_clock_secs=b.get("wall_clock_secs"),
            )
        )

    def run(self) -> RunResult:
        if self.spec.get("kind") != "pr-triage":
            raise ValueError(f"unsupported loop kind: {self.spec.get('kind')!r}")
        if self.spec.get("paused"):
            return self._finish(RunResult("clean", note="paused"))

        try:
            self.ledger.tick()
        except BudgetExceeded as e:
            return self._finish(RunResult("escalated", note=str(e)))

        prior = self.state.read_section(self.loop_id)
        cursor = prior.get("cursor")  # newest updated_at seen last time, or None

        # Fetch open PRs through the guard. A ConnectorError is either injection in
        # a PR body (fatal — escalate, never act on it) or an unreachable API
        # (fatal — escalate, don't guess). Both stop the run cleanly.
        try:
            raw = self.connector.call_tool("list_pull_requests", {"state": "open", "per_page": 100})
        except ConnectorError as e:
            return self._finish(RunResult("escalated", note=f"connector refused/failed (fatal): {e}"))
        try:
            prs = json.loads(raw)
        except json.JSONDecodeError as e:
            return self._finish(RunResult("escalated", note=f"unparseable connector return: {e}"))
        if not isinstance(prs, list):
            return self._finish(RunResult("escalated", note="connector return was not a PR list"))

        findings: list[Finding] = []
        newest = cursor
        for pr in prs:
            updated = pr.get("updated_at") or ""
            if newest is None or updated > newest:
                newest = updated
            # Cursor gate: skip PRs not touched since we last looked.
            if cursor is not None and updated <= cursor:
                continue
            number = pr.get("number")
            title = pr.get("title") or "(no title)"
            findings.append(Finding(classify_pr(pr), f"PR: {title}", f"#{number}"))

        actionable = [f for f in findings if f.bucket in ("high", "watch")]
        if not actionable:
            note = "no PRs updated since cursor" if cursor is not None else "no open pull requests"
            return self._finish(RunResult("clean", note=note, cursors={"cursor": newest or ""}))

        return self._finish(RunResult("found", findings=findings, cursors={"cursor": newest or ""}))

    def _finish(self, res: RunResult) -> RunResult:
        ts = _utc_now()
        # RunResult.cursors carries {"cursor": <ts>} for this loop kind; fall back
        # to the prior cursor on a run that didn't advance it (e.g. escalation).
        cursor = (res.cursors or {}).get("cursor")
        if cursor is None:
            cursor = self.state.read_section(self.loop_id).get("cursor")
        section = {
            "phase": self.spec.get("phase", "L1"),
            "last_run": ts,
            "last_result": res.result,
            "cursor": cursor,
            "findings": [f.__dict__ for f in res.findings],
            "note": res.note,
            "tokens_spent": self.ledger.tokens_spent,
        }
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
