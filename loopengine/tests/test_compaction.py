"""Tests for context compaction + structured note-taking. All deterministic —
the summarizer is an injected callable; no model, no network."""

from __future__ import annotations

from loopengine.compaction import (
    Compactor,
    Message,
    Notebook,
    estimate_tokens,
    extractive_summary,
)
from loopengine.state import StateStore


# -- token estimate ---------------------------------------------------------

def test_estimate_tokens_is_monotonic_and_roughly_quarter():
    assert estimate_tokens("") == 0
    assert estimate_tokens("abcd") == 1
    assert estimate_tokens("a" * 400) == 100
    # monotonic: more text never estimates fewer tokens
    assert estimate_tokens("a" * 401) >= estimate_tokens("a" * 400)


# -- compaction controller --------------------------------------------------

def test_below_threshold_is_a_noop():
    msgs = [Message("user", "short"), Message("assistant", "also short")]
    res = Compactor(threshold_tokens=10_000).maybe_compact(msgs)
    assert res.compacted is False
    assert res.messages == msgs
    assert res.tokens_before == res.tokens_after


def test_compaction_preserves_pinned_and_recent_drops_older():
    pinned = Message("system", "TASK: keep the build green", pinned=True)
    older = [Message("assistant", "x" * 4000) for _ in range(5)]
    recent = [Message("user", "latest-1"), Message("assistant", "latest-2")]
    msgs = [pinned, *older, *recent]

    comp = Compactor(threshold_tokens=1000, keep_recent=2, summarizer=lambda ms: "SUMMARY")
    res = comp.maybe_compact(msgs)

    assert res.compacted is True
    assert res.dropped == 5
    # pinned first, then exactly one (pinned) summary message, then the recent tail
    assert res.messages[0] is pinned
    assert res.messages[1].pinned and res.messages[1].content.endswith("SUMMARY")
    assert [m.content for m in res.messages[-2:]] == ["latest-1", "latest-2"]
    # compaction must actually shrink the transcript
    assert res.tokens_after < res.tokens_before


def test_injected_summarizer_receives_only_older_messages():
    seen: list[str] = []

    def spy(ms):
        seen.extend(m.content for m in ms)
        return "S"

    msgs = [Message("assistant", "y" * 8000) for _ in range(4)] + [Message("user", "tail")]
    Compactor(threshold_tokens=500, keep_recent=1, summarizer=spy).maybe_compact(msgs)
    assert "tail" not in seen  # the recent tail is kept verbatim, never summarized


# -- default extractive summarizer ------------------------------------------

def test_extractive_summary_keeps_decisions_drops_tool_output():
    msgs = [
        Message("assistant", "Decided to cap iterations at 3.\nrandom chatter line"),
        Message("tool", "HUGE TOOL DUMP that must be dropped " * 50),
        Message("assistant", "Open bug: SHA verifier escalates on missing repo"),
    ]
    summary = extractive_summary(msgs)
    assert "Decided to cap iterations at 3." in summary
    assert "Open bug: SHA verifier escalates on missing repo" in summary
    assert "HUGE TOOL DUMP" not in summary  # tool role dropped wholesale
    assert "random chatter line" not in summary  # no salient marker


def test_extractive_summary_handles_no_salient_lines():
    summary = extractive_summary([Message("assistant", "just chatter\nmore chatter")])
    assert "no salient" in summary.lower()


# -- structured note-taking -------------------------------------------------

def test_notebook_roundtrips_and_preserves_other_section_keys(tmp_path):
    state = StateStore(tmp_path / "s.json")
    state.write_section("loopA", {"phase": "L1", "last_run": "2026-06-30T00:00:00Z"})

    nb = Notebook(state, "loopA")
    nb.add("decision: stay at L1 until boring")
    nb.add("  ")  # whitespace-only is ignored
    nb.add("open: needs a second connector")

    assert nb.notes() == [
        "decision: stay at L1 until boring",
        "open: needs a second connector",
    ]
    # other keys in the section are untouched
    section = state.read_section("loopA")
    assert section["phase"] == "L1" and section["last_run"] == "2026-06-30T00:00:00Z"

    nb.clear()
    assert nb.notes() == []
    assert state.read_section("loopA")["phase"] == "L1"  # clear only drops notes
