"""Tests for the L2 GitHub proposer — deterministic, no network, no token."""

from __future__ import annotations

import pytest

from loopengine.assisted import AssistedResult
from loopengine.proposer import (
    GitHubProposer,
    ProposeError,
    render_pr_body,
    repo_slug_from_remote,
)

SPEC = {
    "id": "fix-parser",
    "kind": "assisted-fix",
    "phase": "L2",
    "target": {"repo": "/repo", "base_ref": "main"},
    "task": "Fix the failing unit test in the parser module.",
    "test_command": "python -m pytest -q",
    "budget": {"max_iterations": 3},
}

PROPOSED = AssistedResult(
    "proposed",
    branch="loop/fix-parser-abc1234",
    commit="deadbeef",
    attempts=2,
    reflections=["attempt 1: tests failed (exit 1): boom"],
)


class FakeAPI:
    def __init__(self) -> None:
        self.calls: list[dict] = []

    def create_pull_request(self, slug, head, base, title, body):
        self.calls.append(
            {"slug": slug, "head": head, "base": base, "title": title, "body": body}
        )
        return {"html_url": f"https://github.com/{slug}/pull/7", "number": 7}


def make_git(log: list[list[str]], remote_url: str = "https://github.com/o/r.git"):
    def git(repo: str, *args: str) -> str:
        log.append([repo, *args])
        if args[:2] == ("remote", "get-url"):
            return remote_url + "\n"
        return ""

    return git


def test_slug_parsing_https_and_ssh():
    assert repo_slug_from_remote("https://github.com/krishddd/Strive_Engineering.git") == (
        "krishddd/Strive_Engineering"
    )
    assert repo_slug_from_remote("git@github.com:owner/repo.git") == "owner/repo"
    assert repo_slug_from_remote("https://github.com/owner/repo") == "owner/repo"
    with pytest.raises(ProposeError):
        repo_slug_from_remote("https://gitlab.com/owner/repo.git")


def test_happy_path_pushes_then_opens_pr():
    log: list[list[str]] = []
    api = FakeAPI()
    out = GitHubProposer(api, git=make_git(log)).propose(SPEC, PROPOSED)

    push = next(c for c in log if c[1] == "push")
    # Explicit refspec, never forced.
    assert push == ["/repo", "push", "origin",
                    "loop/fix-parser-abc1234:refs/heads/loop/fix-parser-abc1234"]
    assert not any("--force" in c or "-f" in c for c in log)

    call = api.calls[0]
    assert call["slug"] == "o/r"
    assert call["head"] == "loop/fix-parser-abc1234"
    assert call["base"] == "main"
    assert out == {"url": "https://github.com/o/r/pull/7", "number": 7}


def test_pr_body_carries_verifier_evidence():
    body = render_pr_body(SPEC, PROPOSED)
    assert "python -m pytest -q" in body  # what verified it
    assert "`deadbeef`" in body  # the verified commit
    assert "Attempts: 2" in body
    assert "attempt 1: tests failed" in body  # reflexion trail
    assert "a human merges" in body  # L2 posture stated on the PR itself


def test_refuses_non_proposed_result():
    api = FakeAPI()
    escalated = AssistedResult("escalated", branch="loop/x-abc", note="tampering")
    with pytest.raises(ProposeError, match="escalated"):
        GitHubProposer(api, git=make_git([])).propose(SPEC, escalated)
    assert api.calls == []


def test_refuses_non_loop_branch():
    api = FakeAPI()
    log: list[list[str]] = []
    hijacked = AssistedResult("proposed", branch="main", commit="deadbeef", attempts=1)
    with pytest.raises(ProposeError, match="non-loop branch"):
        GitHubProposer(api, git=make_git(log)).propose(SPEC, hijacked)
    assert log == []  # nothing was pushed
    assert api.calls == []


def test_explicit_slug_skips_remote_lookup():
    log: list[list[str]] = []
    api = FakeAPI()
    GitHubProposer(api, git=make_git(log)).propose(SPEC, PROPOSED, slug="me/mine")
    assert not any(c[1] == "remote" for c in log)
    assert api.calls[0]["slug"] == "me/mine"
