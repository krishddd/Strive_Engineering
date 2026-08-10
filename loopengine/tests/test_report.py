"""Tests for the markdown report — the L1 'surface the findings' step."""

from __future__ import annotations

import json

from loopengine.cli import main
from loopengine.report import (
    ACTIONABLE_RESULTS,
    CLOSE_MARKER,
    is_actionable,
    render_markdown,
    render_resolved_markdown,
    trailing_clean,
)

FOUND_SECTION = {
    "phase": "L1",
    "last_run": "2026-07-06T05:00:00Z",
    "last_result": "found",
    "tokens_spent": 0,
    "note": "",
    "findings": [
        {"bucket": "high", "text": "fix: verifier scored errors as defended", "sha": "393c2ba"},
        {"bucket": "watch", "text": "feat: T32 benchmark — AgentDojo", "sha": "d53be0e"},
        {"bucket": "noise", "text": "Merge pull request #34", "sha": "448ecc2"},
    ],
}


def test_actionable_results_match_scheduler_notify_set():
    from loopengine.scheduler import NOTIFY_RESULTS

    assert ACTIONABLE_RESULTS == NOTIFY_RESULTS


def test_is_actionable():
    assert is_actionable(FOUND_SECTION)
    assert not is_actionable({"last_result": "clean"})
    assert not is_actionable({})


def test_render_groups_buckets_and_cites_shas():
    md = render_markdown("sec-triage", FOUND_SECTION)
    assert "# Loop report: `sec-triage`" in md
    assert "**found**" in md
    assert md.index("High — look at these (1)") < md.index("Watch — worth a skim (1)")
    assert "`393c2ba` fix: verifier scored errors as defended" in md
    assert "— AgentDojo" in md  # non-ASCII survives rendering


def test_render_neutralizes_backticks_in_untrusted_text():
    section = dict(FOUND_SECTION)
    section["findings"] = [{"bucket": "high", "text": "evil ``` breakout", "sha": "abc1234"}]
    md = render_markdown("x", section)
    assert "```" not in md


CLEAN_SECTION = {"phase": "L1", "last_run": "2026-07-21T07:43:54Z", "last_result": "clean", "note": "no new commits"}


def test_trailing_clean_counts_only_the_tail_streak():
    assert trailing_clean(["found", "clean", "clean", "clean"]) == 3
    assert trailing_clean(["clean", "found"]) == 0
    assert trailing_clean([]) == 0


def test_resolved_banner_states_it_is_resolved_and_marks_close_past_threshold():
    md = render_resolved_markdown("ci-self-triage", CLEAN_SECTION, consecutive_clean=3, close_after=7)
    assert "Resolved — nothing outstanding" in md
    assert "**3**" in md
    assert CLOSE_MARKER not in md  # below threshold: edit, don't close
    closed = render_resolved_markdown("ci-self-triage", CLEAN_SECTION, consecutive_clean=7, close_after=7)
    assert CLOSE_MARKER in closed


def test_cli_resolved_emits_banner_and_counts_streak(tmp_path, capsys):
    state = tmp_path / "state.json"
    state.write_text(json.dumps({"version": 1, "loops": {"t": CLEAN_SECTION}}), encoding="utf-8")
    runlog = tmp_path / "state.runlog.jsonl"
    runlog.write_text(
        "\n".join(
            json.dumps({"loop": "t", "result": r})
            for r in ["found", "clean", "clean"]
        )
        + "\n",
        encoding="utf-8",
    )
    # Plain report on a clean run: nothing to publish.
    assert main(["report", str(state), "t"]) == 1
    capsys.readouterr()
    # --resolved: banner + streak of 2 from the run log, exit 0.
    assert main(["report", str(state), "t", "--resolved", "--close-after", "7"]) == 0
    out = capsys.readouterr().out
    assert "Resolved — nothing outstanding" in out
    assert "**2**" in out
    assert CLOSE_MARKER not in out


def test_cli_report_exit_codes(tmp_path, capsys):
    state = tmp_path / "state.json"
    state.write_text(
        json.dumps({"version": 1, "loops": {"t": FOUND_SECTION, "quiet": {"last_result": "clean"}}}),
        encoding="utf-8",
    )
    assert main(["report", str(state), "t"]) == 0
    assert "# Loop report" in capsys.readouterr().out
    # Clean run: nothing to publish -> exit 1, no body on stdout.
    assert main(["report", str(state), "quiet"]) == 1
    assert capsys.readouterr().out == ""
    # --even-clean forces a body (e.g. for a status page).
    assert main(["report", str(state), "quiet", "--even-clean"]) == 0
    # Unknown loop -> exit 1.
    assert main(["report", str(state), "nope"]) == 1
