"""Tests for the markdown report — the L1 'surface the findings' step."""

from __future__ import annotations

import json

from loopengine.cli import main
from loopengine.report import ACTIONABLE_RESULTS, is_actionable, render_markdown

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
