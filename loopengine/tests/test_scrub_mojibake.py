"""Tests for the mojibake remediation pass (scripts/scrub_mojibake.py)."""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path

_SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "scrub_mojibake.py"


def _load():
    spec = importlib.util.spec_from_file_location("scrub_mojibake", _SCRIPT)
    mod = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    spec.loader.exec_module(mod)
    return mod


scrub = _load()

# The real corruption seen in .loop-state/state.json: an em-dash mangled by a
# cp1252-decoded UTF-8 stream.
MANGLED = "feat: T32 external benchmark â€” AgentDojo"
CLEAN = "feat: T32 external benchmark — AgentDojo"


def test_demojibake_recovers_the_em_dash():
    assert scrub.demojibake(MANGLED) == CLEAN


def test_demojibake_is_idempotent_and_safe_on_clean_text():
    assert scrub.demojibake(CLEAN) == CLEAN
    assert scrub.demojibake("plain ascii") == "plain ascii"
    assert scrub.demojibake("café") == "café"  # legit non-ASCII is untouched


def test_scrub_file_fixes_nested_strings(tmp_path):
    state = tmp_path / "state.json"
    state.write_text(
        json.dumps({"loops": {"x": {"findings": [{"text": MANGLED, "sha": "d53be0e"}]}}}),
        encoding="utf-8",
    )
    count = scrub.scrub_file(state)
    assert count == 1
    data = json.loads(state.read_text(encoding="utf-8"))
    assert data["loops"]["x"]["findings"][0]["text"] == CLEAN
    # Re-running is a no-op.
    assert scrub.scrub_file(state) == 0
