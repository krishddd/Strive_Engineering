"""Git worktree isolation for assisted-fix loops.

When a loop *changes* code, it must do so in an isolated working directory so a
broken candidate never touches the main tree and parallel attempts never collide
(the Orchestrator-Workers pattern). A git worktree is a separate working
directory on its own branch that shares the repo's object store.

On a rejected/failed attempt the worktree AND its throwaway branch are removed.
On success the worktree is removed but the branch is kept, so a human can review
and merge it — L2 proposes, it never auto-merges.
"""

from __future__ import annotations

import shutil
import subprocess
import tempfile
from pathlib import Path

from .core import Loopguard


class WorktreeError(RuntimeError):
    pass


class Worktree:
    """Create/destroy an isolated worktree+branch off ``base_ref``."""

    def __init__(self, repo: str, base_ref: str, branch: str, guard: Loopguard | None = None) -> None:
        self.repo = repo
        self.base_ref = base_ref
        self.branch = branch
        self.guard = guard
        self.path: Path | None = None

    def _git(self, *args: str, cwd: str | None = None) -> str:
        proc = subprocess.run(
            ["git", "-C", cwd or self.repo, *args],
            capture_output=True,
            text=True,
            check=False,
        )
        if proc.returncode != 0:
            raise WorktreeError(proc.stderr.strip() or f"git {' '.join(args)} failed")
        return proc.stdout

    def create(self) -> Path:
        tmp = tempfile.mkdtemp(prefix="loopwt-")
        # Best-effort: clear a stale branch of the same name so create is idempotent.
        try:
            self._git("branch", "-D", self.branch)
        except WorktreeError:
            pass
        # `git worktree add -b <branch> <path> <base>` — new branch off base_ref.
        self._git("worktree", "add", "--quiet", "-b", self.branch, tmp, self.base_ref)
        self.path = Path(tmp)
        return self.path

    def stage_all_and_diff(self) -> str:
        """Stage everything in the worktree and return the staged unified diff
        (includes added/removed files). This is what the integrity scanner sees."""
        if not self.path:
            raise WorktreeError("worktree not created")
        self._git("add", "-A", cwd=str(self.path))
        return self._git("diff", "--cached", cwd=str(self.path))

    def commit(self, message: str) -> str:
        """Commit staged changes on the branch; return the new commit SHA."""
        if not self.path:
            raise WorktreeError("worktree not created")
        self._git(
            "-c", "user.name=loopengine",
            "-c", "user.email=loopengine@local",
            "commit", "--quiet", "-m", message,
            cwd=str(self.path),
        )
        return self._git("rev-parse", "HEAD", cwd=str(self.path)).strip()

    def run(self, command: str) -> tuple[int, str]:
        """Run a shell command in the worktree, guarded by loopguard.

        Returns (exit_code, combined_output). A command the guard blocks returns
        a synthetic non-zero code and never executes.
        """
        if not self.path:
            raise WorktreeError("worktree not created")
        if self.guard:
            decision = self.guard.check_command(command)
            if not decision.allowed:
                return 126, f"blocked by guard [{decision.rule}]: {decision.reason}"
        proc = subprocess.run(
            command, shell=True, cwd=str(self.path),
            capture_output=True, text=True, check=False,
        )
        return proc.returncode, (proc.stdout + proc.stderr)

    def cleanup(self, keep_branch: bool = False) -> None:
        """Remove the worktree; optionally keep the branch (for review)."""
        if self.path and self.path.exists():
            try:
                self._git("worktree", "remove", "--force", str(self.path))
            except WorktreeError:
                shutil.rmtree(self.path, ignore_errors=True)
                try:
                    self._git("worktree", "prune")
                except WorktreeError:
                    pass
        if not keep_branch:
            # Best-effort delete of the throwaway branch.
            try:
                self._git("branch", "-D", self.branch)
            except WorktreeError:
                pass
        self.path = None

    def __enter__(self) -> "Worktree":
        self.create()
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        # Default exit keeps nothing; callers that succeed call cleanup(keep_branch=True)
        # explicitly before the context closes.
        if self.path is not None:
            self.cleanup(keep_branch=False)
