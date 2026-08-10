"""Tests for the pr-triage loop — read-only open-PR triage over the guarded connector.

Deterministic: a fake connector returns canned PR payloads, so no network, no
token, no loopguard binary is needed. (The end-to-end injection-gate behavior of
the real GitHubTransport is covered in test_github_connector.py.)
"""

from __future__ import annotations

import json

from loopengine.connectors import ConnectorError
from loopengine.prtriage import PRTriageLoop, classify_pr
from loopengine.state import StateStore

SPEC = {
    "id": "pt",
    "kind": "pr-triage",
    "phase": "L1",
    "target": {"slug": "o/r"},
    "budget": {"max_iterations": 1},
}


class FakeConnector:
    """Stands in for a GuardedConnector: returns a canned JSON string, or raises."""

    def __init__(self, prs=None, error: Exception | None = None):
        self._payload = json.dumps(prs if prs is not None else [])
        self._error = error
        self.calls: list[tuple[str, dict]] = []

    def call_tool(self, tool: str, args=None):
        self.calls.append((tool, args or {}))
        if self._error:
            raise self._error
        return self._payload


def _pr(number, title, updated, draft=False, head="feature/x"):
    return {"number": number, "title": title, "updated_at": updated, "draft": draft, "head": head}


def test_classify_buckets():
    assert classify_pr(_pr(1, "add docs", "t", draft=True)) == "noise"
    assert classify_pr(_pr(2, "fix: crash", "t")) == "high"
    assert classify_pr(_pr(3, "whatever", "t", head="loop/auto-fix")) == "high"
    assert classify_pr(_pr(4, "refactor thing", "t")) == "watch"


def test_first_run_reports_all_open_prs_and_sets_cursor(tmp_path):
    state = StateStore(tmp_path / "state.json")
    conn = FakeConnector([
        _pr(1, "fix: null deref", "2026-08-01T00:00:00Z"),
        _pr(2, "chore: bump", "2026-08-02T00:00:00Z", draft=True),
    ])
    res = PRTriageLoop(SPEC, state, conn).run()
    assert res.result == "found"
    assert conn.calls[0][0] == "list_pull_requests"
    section = state.read_section("pt")
    assert section["cursor"] == "2026-08-02T00:00:00Z"  # newest updated_at seen
    high = [f for f in section["findings"] if f["bucket"] == "high"]
    assert high and high[0]["sha"] == "#1"


def test_cursor_gate_makes_a_quiet_day_clean(tmp_path):
    state = StateStore(tmp_path / "state.json")
    prs = [_pr(1, "fix: x", "2026-08-01T00:00:00Z")]
    PRTriageLoop(SPEC, state, FakeConnector(prs)).run()  # first run: found, cursor set
    res2 = PRTriageLoop(SPEC, state, FakeConnector(prs)).run()  # nothing newer
    assert res2.result == "clean"
    assert "since cursor" in res2.note


def test_new_activity_after_cursor_is_reported(tmp_path):
    state = StateStore(tmp_path / "state.json")
    PRTriageLoop(SPEC, state, FakeConnector([_pr(1, "fix: x", "2026-08-01T00:00:00Z")])).run()
    res = PRTriageLoop(
        state=state, spec=SPEC,
        connector=FakeConnector([
            _pr(1, "fix: x", "2026-08-01T00:00:00Z"),
            _pr(2, "fix: y", "2026-08-05T00:00:00Z"),
        ]),
    ).run()
    assert res.result == "found"
    assert [f.sha for f in res.findings] == ["#2"]  # only the newly-updated PR


def test_connector_refusal_escalates_not_crashes(tmp_path):
    state = StateStore(tmp_path / "state.json")
    conn = FakeConnector(error=ConnectorError("high-severity prompt injection in github.list_pull_requests"))
    res = PRTriageLoop(SPEC, state, conn).run()
    assert res.result == "escalated"
    assert "fatal" in res.note


def test_paused_is_a_clean_noop(tmp_path):
    state = StateStore(tmp_path / "state.json")
    res = PRTriageLoop({**SPEC, "paused": True}, state, FakeConnector([_pr(1, "fix", "t")])).run()
    assert res.result == "clean" and res.note == "paused"
