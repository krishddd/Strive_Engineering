"""L2 proposal delivery — push the verified branch and open a pull request.

CLAUDE.md §5 defines L2 as "proposes a patch (PR, not a direct commit)". Until
now the loop stopped at a local branch; this module carries the proposal the
last mile to GitHub. It is deliberately *not* a general write connector — §8
bans those below L3 — but the one sanctioned L2 write: push a `loop/*` branch,
open a PR whose body carries the verifier's evidence. See docs/safety.md.

Structural rules (enforced here, not just documented):

* Only branches under ``loop/`` may be pushed — the proposer refuses anything
  else, so it cannot be repurposed to push to main.
* The push refspec is explicit and never forced — no history rewrite possible.
* A PR is opened only for a ``proposed`` result — an escalated or errored run
  has nothing reviewable and must not reach GitHub.

Both effects (the git push and the API call) are injected, so tests are
deterministic with no network and no token.
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import urllib.error
import urllib.request
from typing import Any, Callable, Protocol


class ProposeError(RuntimeError):
    """The proposal could not be delivered (refused or transport failure)."""


# -- repo slug -----------------------------------------------------------------

_SLUG_RE = re.compile(r"github\.com[:/]([^/]+)/([^/\s]+?)(?:\.git)?/?$")


def repo_slug_from_remote(url: str) -> str:
    """Extract ``owner/name`` from an https or ssh GitHub remote URL."""
    m = _SLUG_RE.search(url.strip())
    if not m:
        raise ProposeError(f"cannot parse a GitHub repo slug from remote {url!r}")
    return f"{m.group(1)}/{m.group(2)}"


# -- injected effects ----------------------------------------------------------

# Runs a git command in the target repo; returns stdout. Injected for tests.
GitRunner = Callable[..., str]


def default_git_runner(repo: str, *args: str) -> str:
    proc = subprocess.run(
        ["git", "-C", repo, *args],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=False,
    )
    if proc.returncode != 0:
        raise ProposeError(proc.stderr.strip() or f"git {' '.join(args)} failed")
    return proc.stdout


class PullRequestAPI(Protocol):
    """Minimal surface: open a PR, return the API's response object."""

    def create_pull_request(
        self, slug: str, head: str, base: str, title: str, body: str
    ) -> dict[str, Any]: ...


class GitHubRestAPI:
    """Stdlib-only GitHub REST client (no SDK, per repo conventions)."""

    def __init__(self, token: str | None = None, api_base: str = "https://api.github.com") -> None:
        self.token = token or os.environ.get("GITHUB_TOKEN") or os.environ.get("GH_TOKEN")
        if not self.token:
            raise ProposeError("no GitHub token: set GITHUB_TOKEN or GH_TOKEN")
        self.api_base = api_base.rstrip("/")

    def create_pull_request(
        self, slug: str, head: str, base: str, title: str, body: str
    ) -> dict[str, Any]:
        payload = json.dumps({"title": title, "head": head, "base": base, "body": body})
        req = urllib.request.Request(
            f"{self.api_base}/repos/{slug}/pulls",
            data=payload.encode("utf-8"),
            method="POST",
            headers={
                "Authorization": f"Bearer {self.token}",
                "Accept": "application/vnd.github+json",
                "Content-Type": "application/json",
                "User-Agent": "loopengine-proposer",
            },
        )
        try:
            with urllib.request.urlopen(req, timeout=30) as resp:
                return json.loads(resp.read().decode("utf-8"))
        except urllib.error.HTTPError as e:
            detail = e.read().decode("utf-8", errors="replace")[:500]
            raise ProposeError(f"GitHub API {e.code} opening PR: {detail}") from e
        except urllib.error.URLError as e:
            raise ProposeError(f"GitHub unreachable: {e.reason}") from e


# -- the proposer ----------------------------------------------------------------


def render_pr_body(spec: dict[str, Any], result: Any) -> str:
    """The PR body IS the verifier evidence — a reviewer should see at a glance
    what was checked, not just what changed."""
    reflections = "\n".join(f"- {r}" for r in result.reflections) or "- (first attempt passed)"
    return (
        f"## Proposed by assisted-fix loop `{spec['id']}`\n\n"
        f"**Task:** {spec['task']}\n\n"
        f"### Verifier evidence\n"
        f"- Test command passed in an isolated worktree: `{spec['test_command']}`\n"
        f"- Integrity scan: clean (no verifier tampering in the diff)\n"
        f"- Attempts: {result.attempts} (cap {spec.get('budget', {}).get('max_iterations', '?')})\n"
        f"- Commit: `{result.commit}`\n\n"
        f"### Reflections (failed attempts fed back to the maker)\n{reflections}\n\n"
        f"---\n"
        f"_L2 loop output: the loop proposes, a human merges. Opened by loopengine._\n"
    )


class GitHubProposer:
    """Deliver one ``proposed`` AssistedResult as a GitHub pull request."""

    def __init__(
        self,
        api: PullRequestAPI,
        git: GitRunner = default_git_runner,
        remote: str = "origin",
    ) -> None:
        self.api = api
        self.git = git
        self.remote = remote

    def propose(self, spec: dict[str, Any], result: Any, slug: str | None = None) -> dict[str, Any]:
        if result.result != "proposed":
            raise ProposeError(f"refusing to open a PR for a {result.result!r} result")
        branch = result.branch or ""
        if not branch.startswith("loop/"):
            raise ProposeError(f"refusing to push non-loop branch {branch!r}")

        repo = spec["target"]["repo"]
        base = spec["target"].get("base_ref", "main")
        if slug is None:
            slug = repo_slug_from_remote(self.git(repo, "remote", "get-url", self.remote).strip())

        # Explicit refspec, never --force: the proposer cannot rewrite history.
        self.git(repo, "push", self.remote, f"{branch}:refs/heads/{branch}")

        pr = self.api.create_pull_request(
            slug,
            head=branch,
            base=base,
            title=f"loop({spec['id']}): {spec['task']}"[:120],
            body=render_pr_body(spec, result),
        )
        return {"url": pr.get("html_url", ""), "number": pr.get("number")}
