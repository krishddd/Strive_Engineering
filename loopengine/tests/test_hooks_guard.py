"""Tests for the interactive-session safety hook (scripts/hooks/guard_bash.py).

The hook is the enforcement layer CLAUDE.md §3/§8 mandates: prose rules turned
into a check that holds every time. We test both the pure ``evaluate`` predicate
and the real stdin→exit-code contract Claude Code relies on (exit 2 = block).
"""

from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
from pathlib import Path

_HOOK = Path(__file__).resolve().parents[2] / "scripts" / "hooks" / "guard_bash.py"


def _load():
    spec = importlib.util.spec_from_file_location("guard_bash", _HOOK)
    mod = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    spec.loader.exec_module(mod)
    return mod


guard = _load()


BLOCKED = [
    "git push --force origin main",
    "git push -f origin main",
    "git push --force-with-lease origin main",
    "git push --mirror origin",
    "git push origin +main:main",
    "git reset --hard HEAD~3",
    "git filter-branch --tree-filter 'rm secrets' HEAD",
    "rm -rf build/",
    "rm -fr /tmp/x",
    "rm -r -f node_modules",
    "cd x && git push --force origin main",
]

ALLOWED = [
    "git push origin main",
    "git status",
    "git log --oneline -5",
    "git commit -m 'ok'",
    "git reset HEAD~1",          # soft reset keeps work — not blocked
    "rm -f stale.txt",           # force without recurse — not a blast-radius delete
    "rm -r emptydir",            # recurse without force — prompts, not silent
    "cargo build --release",
    "python -m pytest -q",
]


def test_evaluate_blocks_the_dangerous_shapes():
    for cmd in BLOCKED:
        blocked, reason = guard.evaluate(cmd)
        assert blocked, f"should have blocked: {cmd}"
        assert reason


def test_evaluate_allows_ordinary_commands():
    for cmd in ALLOWED:
        blocked, _ = guard.evaluate(cmd)
        assert not blocked, f"should have allowed: {cmd}"


def _run_hook(payload: dict) -> int:
    proc = subprocess.run(
        [sys.executable, str(_HOOK)],
        input=json.dumps(payload),
        capture_output=True,
        text=True,
    )
    return proc.returncode


def test_hook_exit_codes_match_claude_code_contract():
    assert _run_hook({"tool_input": {"command": "git push --force origin main"}}) == 2
    assert _run_hook({"tool_input": {"command": "git status"}}) == 0
    # Malformed / empty payloads fail open (never wedge the session).
    assert _run_hook({}) == 0
    assert _run_hook({"tool_input": {}}) == 0
