"""Read-only git inspection of a triage target.

Every function here is strictly read-only (``rev-parse``, ``log``,
``cat-file``). The runtime additionally routes any shell command through the
loopguard denylist, so a write verb against the target is refused even if a bug
introduced one here.
"""

from __future__ import annotations

import subprocess
from dataclasses import dataclass


class GitError(RuntimeError):
    """A fatal, non-recoverable git problem (missing/unreadable repo)."""


def _git(repo: str, *args: str) -> str:
    proc = subprocess.run(
        ["git", "-C", repo, *args],
        capture_output=True,
        text=True,
        check=False,
    )
    if proc.returncode != 0:
        raise GitError(proc.stderr.strip() or f"git {' '.join(args)} failed")
    return proc.stdout


def is_git_repo(repo: str) -> bool:
    try:
        _git(repo, "rev-parse", "--git-dir")
        return True
    except GitError:
        return False


def resolve(repo: str, ref: str) -> str:
    return _git(repo, "rev-parse", ref).strip()


@dataclass
class Commit:
    sha: str
    short: str
    date: str
    subject: str


def commits(repo: str, ref: str, since_cursor: str | None, first_run_since: str) -> list[Commit]:
    """New commits on ``ref``.

    If ``since_cursor`` is set, return commits in ``cursor..ref``. Otherwise
    (first run) return commits within the ``first_run_since`` window.
    """
    fmt = "%H%x1f%h%x1f%cd%x1f%s"
    if since_cursor:
        rng = f"{since_cursor}..{ref}"
        out = _git(repo, "log", rng, f"--format={fmt}", "--date=short")
    else:
        out = _git(repo, "log", ref, f"--since={first_run_since}", f"--format={fmt}", "--date=short")
    result: list[Commit] = []
    for line in out.splitlines():
        if not line.strip():
            continue
        full, short, date, subject = line.split("\x1f")
        result.append(Commit(full, short, date, subject))
    return result


def ahead_behind(repo: str, base: str, tip: str) -> tuple[int, int]:
    """Return (ahead, behind) of ``tip`` relative to ``base``."""
    out = _git(repo, "rev-list", "--left-right", "--count", f"{base}...{tip}").split()
    behind, ahead = int(out[0]), int(out[1])
    return ahead, behind
