"""Tests for the LLM agent maker.

The LLM call is faked, so these run with no API key and no network — they verify
the maker writes the model's proposed files into the worktree, refuses path
traversal, and drives the full AssistedFixLoop (worktree -> maker -> integrity ->
tests) to a `proposed` branch. A cheating model response is caught by the
integrity gate, exactly as a real one would be.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

from loopengine.assisted import AssistedFixLoop
from loopengine.core import LoopguardUnavailable, find_loopguard
from loopengine.makers import LLMMaker, OpenAICompatibleClient, make_maker
from loopengine.state import StateStore

try:
    find_loopguard()
    HAVE_GUARD = True
except LoopguardUnavailable:
    HAVE_GUARD = False


class FakeClient:
    """Returns a canned files payload; records the prompt it was given."""

    def __init__(self, files: list[dict]) -> None:
        self.files = files
        self.last_user = ""

    def complete_json(self, system: str, user: str, schema: dict) -> dict:
        self.last_user = user
        return {"files": self.files}


def test_llm_maker_writes_proposed_files(tmp_path):
    wt = tmp_path / "wt"
    wt.mkdir()
    (wt / "value.py").write_text("def value():\n    return 1\n")
    maker = LLMMaker(FakeClient([{"path": "value.py", "content": "def value():\n    return 42\n"}]))

    maker(wt, "make value() return 42", reflections=[])

    assert "return 42" in (wt / "value.py").read_text()
    assert "TASK:" in maker.client.last_user  # the task reached the model


def test_llm_maker_refuses_path_traversal(tmp_path):
    wt = tmp_path / "wt"
    wt.mkdir()
    maker = LLMMaker(FakeClient([{"path": "../escape.py", "content": "x = 1\n"}]))
    with pytest.raises(ValueError):
        maker(wt, "task", reflections=[])
    assert not (tmp_path / "escape.py").exists()


def test_make_maker_unknown_type():
    with pytest.raises(ValueError):
        make_maker({"type": "telepathy"})


# -- OpenAI-compatible (NVIDIA NIM) client, no network -----------------------

def test_openai_client_parses_response_via_fake_transport():
    captured = {}

    def transport(payload: dict) -> str:
        captured["model"] = payload["model"]
        # Simulate a chatty model: code fence + prose around the JSON.
        return 'Sure!\n```json\n{"files": [{"path": "a.py", "content": "x = 1\\n"}]}\n```'

    client = OpenAICompatibleClient(model="meta/llama-3.3-70b-instruct", transport=transport)
    out = client.complete_json("sys", "fix it", {"type": "object"})
    assert out["files"][0]["path"] == "a.py"
    assert captured["model"] == "meta/llama-3.3-70b-instruct"


def test_openai_client_handles_reasoning_think_block():
    def transport(payload: dict) -> str:
        return '<think>I should return JSON</think>\n{"files": []}'

    client = OpenAICompatibleClient(model="deepseek-ai/deepseek-r1", transport=transport)
    assert client.complete_json("s", "u", {}) == {"files": []}


def test_openai_client_retries_without_response_format_on_400():
    import urllib.error

    calls = []

    def transport(payload: dict) -> str:
        calls.append("response_format" in payload)
        if "response_format" in payload:
            raise urllib.error.HTTPError("u", 400, "bad response_format", {}, None)
        return '{"files": []}'

    client = OpenAICompatibleClient(model="some/model", transport=transport)
    assert client.complete_json("s", "u", {}) == {"files": []}
    assert calls == [True, False]  # tried with, then retried without


def test_make_maker_nvidia_builds_without_network():
    maker = make_maker({"type": "nvidia", "model": "qwen/qwen3-coder-480b-a35b-instruct"})
    assert isinstance(maker, LLMMaker)
    assert isinstance(maker.client, OpenAICompatibleClient)
    assert maker.client.api_key_env == "NVIDIA_API_KEY"


def test_make_maker_openai_requires_base_url():
    with pytest.raises(ValueError):
        make_maker({"type": "openai", "model": "x"})


def test_nvidia_maker_drives_loop_with_fake_transport(tmp_path):
    # The NVIDIA-backed maker, faked, fixes a file end-to-end via the LLMMaker path.
    wt = tmp_path / "wt"
    wt.mkdir()
    (wt / "value.py").write_text("def value():\n    return 1\n")

    def transport(payload: dict) -> str:
        return '{"files": [{"path": "value.py", "content": "def value():\\n    return 42\\n"}]}'

    maker = make_maker({"type": "nvidia"})
    maker.client.transport = transport  # inject fake transport post-build
    maker(wt, "make value() return 42", reflections=[])
    assert "return 42" in (wt / "value.py").read_text()


@pytest.mark.skipif(not HAVE_GUARD, reason="loopguard binary not built")
def test_llm_maker_drives_assisted_fix_to_proposed(tmp_path):
    # Build a target repo with a failing test.
    repo = tmp_path / "proj"
    repo.mkdir()

    def git(*a):
        subprocess.run(["git", "-C", str(repo), *a], capture_output=True, text=True, check=True)

    git("init", "-q")
    git("config", "user.email", "t@e.com")
    git("config", "user.name", "t")
    git("checkout", "-q", "-b", "main")
    (repo / "value.py").write_text("def value():\n    return 1\n")
    (repo / "test_value.py").write_text("from value import value\n\n\ndef test_value():\n    assert value() == 42\n")
    git("add", "-A")
    git("commit", "-q", "-m", "init")

    # The 'agent' (faked) returns the correct fix.
    maker = LLMMaker(FakeClient([{"path": "value.py", "content": "def value():\n    return 42\n"}]))
    spec = {
        "id": "llm-fix",
        "kind": "assisted-fix",
        "phase": "L2",
        "state_file": str(tmp_path / "state.json"),
        "target": {"repo": str(repo), "base_ref": "main"},
        "task": "make value() return 42",
        "test_command": f'"{sys.executable}" -m pytest -q test_value.py',
        "budget": {"max_iterations": 2},
    }
    res = AssistedFixLoop(spec, StateStore(tmp_path / "state.json"), maker=maker).run()
    assert res.result == "proposed", res.note
    assert res.branch
