#!/usr/bin/env python3
"""PreToolUse guard for interactive Claude Code sessions in this repo.

CLAUDE.md is explicit (§3, §8): the safety rules are *advisory* as prose and must
be turned into a **hook** — the enforcement layer that holds 100% of the time, not
most of the time. The Rust ``loopguard`` denylist already guards *loop-spawned*
commands; this guard covers the other half — the commands a human (or Claude) runs
interactively in this repo.

It is wired as a ``PreToolUse`` hook on the ``Bash`` tool in ``.claude/settings.json``.
Claude Code feeds the tool call as JSON on stdin; a hook exit code of **2** blocks
the call and returns stderr to the model. Any other non-zero is a non-blocking
error. We only ever block (exit 2) or allow (exit 0).

Kept dependency-free and importable so ``evaluate`` can be unit-tested directly.
"""

from __future__ import annotations

import json
import re
import sys

# Each rule: (compiled pattern, human reason). Mirrors CLAUDE.md §8's
# non-negotiables — force-push, destructive recursive delete, history rewrite —
# expressed as the shapes those actually take on a command line.
_RULES: list[tuple[re.Pattern[str], str]] = [
    (
        re.compile(r"\bgit\b.*\bpush\b.*(--force\b|--force-with-lease\b|(?<!\w)-f\b|--mirror\b)"),
        "force-push / mirror-push rewrites remote history (CLAUDE.md §8: no force-push)",
    ),
    (
        # A leading '+' on a refspec is a force push in disguise: `git push origin +main`.
        re.compile(r"\bgit\b.*\bpush\b.*\s\+[\w./-]+:"),
        "a '+refspec' is a force-push in disguise (CLAUDE.md §8: no force-push)",
    ),
    (
        re.compile(r"\bgit\b.*\breset\b.*--hard\b"),
        "git reset --hard discards work irrecoverably (CLAUDE.md §8: no history rewrite)",
    ),
    (
        re.compile(r"\bgit\b.*\b(filter-branch|filter-repo)\b"),
        "history rewrite from inside the repo (CLAUDE.md §8: no history rewrite)",
    ),
    (
        re.compile(r"\bgit\b.*\bpush\b.*\bloop-state\b.*(--force|--force-with-lease|(?<!\w)-f\b)"),
        "never force-push the durable loop-state branch (CLAUDE.md §6/§8)",
    ),
    (
        # rm with a recursive AND force flag (in either order, combined or split).
        re.compile(r"\brm\b\s+(-\w*r\w*f\w*|-\w*f\w*r\w*|-[rf]\s+-[rf])"),
        "rm -rf is a blast-radius delete (CLAUDE.md §8: no rm -rf from a loop)",
    ),
]


def evaluate(command: str) -> tuple[bool, str]:
    """Return (blocked, reason). ``blocked`` True means refuse the command."""
    normalized = " ".join(command.split())
    for pattern, reason in _RULES:
        if pattern.search(normalized):
            return True, reason
    return False, ""


def main() -> int:
    raw = sys.stdin.read()
    try:
        payload = json.loads(raw) if raw.strip() else {}
    except json.JSONDecodeError:
        # Can't parse the hook payload — fail open (exit 0) rather than wedge the
        # session; the loopguard denylist still covers loop-spawned commands.
        return 0

    command = (payload.get("tool_input") or {}).get("command", "")
    if not isinstance(command, str) or not command:
        return 0

    blocked, reason = evaluate(command)
    if blocked:
        print(f"BLOCKED by repo safety hook: {reason}", file=sys.stderr)
        print("If this is genuinely intended, run it yourself outside the agent.", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
