"""L2 assisted-fix loop — propose a verified change, never auto-merge.

Wires together everything the earlier phases built:

  worktree isolation  →  maker proposes an edit  →  checker gates it:
      1. integrity scan of the diff   (reward-hacking / verifier tampering)
      2. injection scan of the task   (indirect prompt injection in the brief)
      3. run the test command         (the ground-truth verifier)
  →  Reflexion: on a *test* failure, feed the reason into the next attempt
  →  bounded by the iteration cap     (no oscillation / no runaway)
  →  on success, commit to the branch and leave it for a human to review.

Hard rules baked in:
* A diff that tampers with the verifier (deletes a test, etc.) is an **immediate
  escalation** — it is a safety event, not something to retry.
* The loop **never merges**. L2 proposes a branch; a human merges. Blast radius is
  a throwaway branch in an isolated worktree.
* Infrastructure git ops (worktree add/stage/commit/reset) are trusted and bypass
  the command guard; only the maker's and test's shell commands are guarded.
"""

from __future__ import annotations

import datetime as _dt
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Protocol

from .budget import Budget, BudgetExceeded, Ledger
from .core import Loopguard
from .gitscan import is_git_repo, resolve
from .state import StateStore
from .worktree import Worktree


def _utc_now() -> str:
    return _dt.datetime.now(_dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


class Maker(Protocol):
    """Edits files in ``worktree_path`` to address ``task``, informed by prior
    ``reflections``. Side-effecting; returns nothing."""

    def __call__(self, worktree_path: Path, task: str, reflections: list[str]) -> None: ...


class ScriptMaker:
    """A maker that runs a configured shell command in the worktree (the
    placeholder for an agent step). The command is guarded by loopguard."""

    def __init__(self, command: str) -> None:
        self.command = command

    def __call__(self, worktree_path: Path, task: str, reflections: list[str]) -> None:
        # Executed via Worktree.run (guarded) by the loop; here we are only the
        # carrier of the command string. The loop invokes it.
        raise NotImplementedError  # ScriptMaker is handled specially by the loop


@dataclass
class AssistedResult:
    result: str  # proposed | escalated | clean | error
    branch: str | None = None
    commit: str | None = None
    attempts: int = 0
    note: str = ""
    reflections: list[str] = field(default_factory=list)


class AssistedFixLoop:
    """Run one assisted-fix cycle for an `assisted-fix` loop spec."""

    def __init__(
        self,
        spec: dict,
        state: StateStore,
        guard: Loopguard | None = None,
        maker: Maker | None = None,
    ) -> None:
        self.spec = spec
        self.state = state
        self.loop_id = spec["id"]
        self.guard = guard or Loopguard()
        self.maker = maker
        b = spec.get("budget", {})
        self.max_attempts = int(b.get("max_iterations", 3))
        self.ledger = Ledger(
            Budget(
                max_tokens=b.get("max_tokens"),
                max_iterations=self.max_attempts,
                wall_clock_secs=b.get("wall_clock_secs"),
            )
        )

    def run(self) -> AssistedResult:
        phase = self.spec.get("phase")
        if phase not in ("L2", "L3"):
            return self._finish(AssistedResult("error", note="assisted-fix requires phase L2 or L3"))
        if self.spec.get("paused"):
            return self._finish(AssistedResult("clean", note="paused"))

        target = self.spec["target"]["repo"]
        base_ref = self.spec["target"].get("base_ref", "main")
        task = self.spec["task"]
        test_command = self.spec["test_command"]
        maker_command = self.spec.get("maker_command")

        if not is_git_repo(target):
            return self._finish(AssistedResult("escalated", note=f"target not a git repo: {target}"))

        # Verify-before-commit (VIGIL): scan the task brief itself for injection.
        inj = self.guard.scan_injection(task)
        if inj.get("severity") == "high":
            return self._finish(
                AssistedResult("escalated", note=f"prompt injection in task brief: {inj['signals']}")
            )

        base_sha = resolve(target, base_ref)[:7]
        branch = f"loop/{self.loop_id}-{base_sha}"
        wt = Worktree(target, base_ref, branch, guard=self.guard)

        reflections: list[str] = []
        try:
            wt.create()
            for attempt in range(1, self.max_attempts + 1):
                try:
                    self.ledger.tick()
                except BudgetExceeded as e:
                    return self._finish(
                        AssistedResult("escalated", branch=None, attempts=attempt - 1,
                                       note=str(e), reflections=reflections),
                        wt, keep_branch=False,
                    )

                # 1. Maker proposes an edit in the isolated worktree.
                self._invoke_maker(wt, maker_command, task, reflections)
                diff = wt.stage_all_and_diff()
                if not diff.strip():
                    reflections.append(f"attempt {attempt}: maker produced no changes")
                    self._reset(wt)
                    continue

                # 2. Integrity gate — tampering is an immediate escalation.
                integrity = self.guard.scan_diff(diff)
                if not integrity.get("clean", True):
                    issues = [f["issue"] for f in integrity.get("findings", [])]
                    return self._finish(
                        AssistedResult(
                            "escalated", branch=None, attempts=attempt,
                            note=f"verifier tampering detected ({issues}) — refusing to retry",
                            reflections=reflections,
                        ),
                        wt, keep_branch=False,
                    )

                # 3. Ground-truth verifier: run the tests in the worktree.
                code, output = wt.run(test_command)
                if code == 0:
                    commit = wt.commit(f"loop({self.loop_id}): {task}\n\nProposed by assisted-fix.")
                    # 4. L3 only: if the change is in the auto-merge allowlist, merge it.
                    if phase == "L3":
                        return self._maybe_auto_merge(wt, target, base_ref, branch, commit, diff, attempt, reflections)
                    # L2: leave the branch for a human to review and merge.
                    return self._finish(
                        AssistedResult(
                            "proposed", branch=branch, commit=commit, attempts=attempt,
                            note="tests pass; branch left for human review (no auto-merge)",
                            reflections=reflections,
                        ),
                        wt, keep_branch=True,
                    )

                # Reflexion: record why it failed, reset, retry.
                tail = "\n".join(output.strip().splitlines()[-8:])
                reflections.append(f"attempt {attempt}: tests failed (exit {code}): {tail}")
                self._reset(wt)

            return self._finish(
                AssistedResult(
                    "escalated", branch=None, attempts=self.max_attempts,
                    note=f"no passing fix in {self.max_attempts} attempts", reflections=reflections,
                ),
                wt, keep_branch=False,
            )
        except Exception as e:  # noqa: BLE001 — surface any infra failure as an escalation
            return self._finish(
                AssistedResult("error", note=f"infra error: {e}", reflections=reflections),
                wt, keep_branch=False,
            )

    # -- L3 auto-merge ------------------------------------------------------

    def _maybe_auto_merge(self, wt, target, base_ref, branch, commit, diff, attempt, reflections):
        """L3: auto-merge the verified change iff it passes the allowlist gate;
        otherwise escalate (leave the branch for review). Auto-merge is a
        fast-forward of base_ref — never a force-push, never a history rewrite."""
        policy = self.spec.get("allowlist")
        if not policy:
            return self._finish(
                AssistedResult("escalated", branch=branch, commit=commit, attempts=attempt,
                               note="L3 set but no allowlist policy — escalating",
                               reflections=reflections),
                wt, keep_branch=True,
            )

        decision = self.guard.check_allowlist(diff, policy)
        if not decision.get("auto_ok"):
            return self._finish(
                AssistedResult("proposed", branch=branch, commit=commit, attempts=attempt,
                               note=f"outside auto-merge allowlist: {decision.get('reasons')}",
                               reflections=reflections),
                wt, keep_branch=True,
            )

        # Safety: never auto-move base_ref if it's the target's checked-out branch.
        try:
            head_branch = wt._git("symbolic-ref", "--short", "HEAD").strip()
        except Exception:  # noqa: BLE001 — detached HEAD etc.
            head_branch = ""
        if head_branch == base_ref:
            return self._finish(
                AssistedResult("proposed", branch=branch, commit=commit, attempts=attempt,
                               note=f"{base_ref} is checked out in the target — refusing auto-merge",
                               reflections=reflections),
                wt, keep_branch=True,
            )

        # Fast-forward base_ref to the verified commit (guarded against races by
        # supplying the expected old value). The worktree branch is then redundant.
        old_base = resolve(target, base_ref)
        wt._git("update-ref", f"refs/heads/{base_ref}", commit, old_base)
        return self._finish(
            AssistedResult("merged", branch=base_ref, commit=commit, attempts=attempt,
                           note=f"auto-merged into {base_ref} (allowlist: {decision['files_changed']} files, "
                                f"{decision['lines_changed']} lines)",
                           reflections=reflections),
            wt, keep_branch=False,
        )

    # -- helpers ------------------------------------------------------------

    def _invoke_maker(self, wt: Worktree, maker_command: str | None, task: str, reflections: list[str]) -> None:
        if self.maker is not None:
            self.maker(wt.path, task, reflections)  # type: ignore[arg-type]
        elif maker_command:
            wt.run(maker_command)  # guarded
        else:
            raise RuntimeError("assisted-fix needs a maker callable or a maker_command in the spec")

    def _reset(self, wt: Worktree) -> None:
        # Trusted infra reset between attempts (bypasses the command guard).
        wt._git("reset", "--hard", "--quiet", cwd=str(wt.path))
        wt._git("clean", "-fdq", cwd=str(wt.path))

    def _finish(self, res: AssistedResult, wt: Worktree | None = None, keep_branch: bool = False) -> AssistedResult:
        if wt is not None:
            wt.cleanup(keep_branch=keep_branch)
        ts = _utc_now()
        self.state.write_section(
            self.loop_id,
            {
                "phase": self.spec.get("phase", "L2"),
                "last_run": ts,
                "last_result": res.result,
                "branch": res.branch,
                "commit": res.commit,
                "attempts": res.attempts,
                "reflections": res.reflections,
                "note": res.note,
            },
        )
        action = {
            "merged": "auto-merged",
            "proposed": "opened-branch",
        }.get(res.result, "escalated-to-human")
        self.state.append_runlog(
            {
                "ts": ts, "loop": self.loop_id, "result": res.result, "action": action,
                "branch": res.branch, "attempts": res.attempts, "note": res.note,
            }
        )
        return res
