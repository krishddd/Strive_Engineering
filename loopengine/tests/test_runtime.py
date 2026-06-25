"""End-to-end tests for the loop runtime against throwaway git repos.

These exercise the full spine: gather -> grounded verify (via the real loopguard
binary) -> state -> escalate. They are skipped automatically if the loopguard
binary has not been built yet.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from loopengine.budget import Budget, BudgetExceeded, Ledger
from loopengine.core import LoopguardUnavailable, find_loopguard
from loopengine.runtime import LoopRuntime, classify
from loopengine.gitscan import Commit
from loopengine.state import StateStore

try:
    find_loopguard()
    HAVE_GUARD = True
except LoopguardUnavailable:
    HAVE_GUARD = False

needs_guard = pytest.mark.skipif(not HAVE_GUARD, reason="loopguard binary not built")


def _git(repo: Path, *args: str) -> str:
    return subprocess.run(
        ["git", "-C", str(repo), *args], capture_output=True, text=True, check=True
    ).stdout.strip()


def _make_repo(tmp_path: Path, n_commits: int) -> Path:
    repo = tmp_path / "target"
    repo.mkdir()
    _git(repo, "init", "-q")
    _git(repo, "config", "user.email", "t@example.com")
    _git(repo, "config", "user.name", "t")
    _git(repo, "checkout", "-q", "-b", "main")
    for i in range(n_commits):
        (repo / f"f{i}.txt").write_text(str(i))
        _git(repo, "add", "-A")
        _git(repo, "commit", "-q", "-m", f"feat: change {i}")
    return repo


def _spec(repo: Path, state: Path) -> dict:
    return {
        "id": "test-triage",
        "kind": "git-commit-triage",
        "phase": "L1",
        "state_file": str(state),
        "target": {"repo": str(repo), "refs": ["main"], "first_run_since": "30 days ago"},
        "budget": {"max_tokens": 50000, "max_iterations": 1},
    }


def test_classify_buckets():
    assert classify(Commit("x", "x", "d", "fix: a security bug")) == "high"
    assert classify(Commit("x", "x", "d", "Merge pull request #1")) == "noise"
    assert classify(Commit("x", "x", "d", "feat: a new thing")) == "watch"


@needs_guard
def test_found_then_clean(tmp_path):
    repo = _make_repo(tmp_path, 3)
    state = StateStore(tmp_path / "state.json")
    spec = _spec(repo, tmp_path / "state.json")

    r1 = LoopRuntime(spec, state).run()
    assert r1.result == "found"
    assert all(f.sha for f in r1.findings)  # every finding is SHA-grounded

    # No new commits -> cursors equal -> valid clean empty run, no invented work.
    r2 = LoopRuntime(spec, state).run()
    assert r2.result == "clean"
    assert "no new commits" in r2.note


@needs_guard
def test_missing_target_is_fatal_escalation(tmp_path):
    state = StateStore(tmp_path / "state.json")
    spec = _spec(tmp_path / "does-not-exist", tmp_path / "state.json")
    r = LoopRuntime(spec, state).run()
    assert r.result == "escalated"


def test_budget_iteration_cap():
    led = Ledger(Budget(max_iterations=1))
    led.tick()
    with pytest.raises(BudgetExceeded):
        led.tick()


def test_state_write_isolates_sections(tmp_path):
    s = StateStore(tmp_path / "state.json")
    s.write_section("a", {"x": 1})
    s.write_section("b", {"y": 2})
    assert s.read_section("a") == {"x": 1}
    assert s.read_section("b") == {"y": 2}
