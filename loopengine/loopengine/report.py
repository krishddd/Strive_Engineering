"""Render a loop's state section as human-facing markdown.

This is the L1 "surface the findings" step: the runtime writes machine state,
and this module turns one loop's section into a report a human actually reads —
in practice, the body of a rolling GitHub issue maintained by CI.

Two disciplines from the scheduler carry over:

* **Triage-inbox** — only actionable results (found / escalated / error /
  proposed / merged) produce a report. A clean run is healthy silence; the CLI
  exits non-zero so the caller skips publishing instead of spamming.
* **Grounded citations** — every finding line carries its short SHA, the same
  SHAs the verifier already resolved against the repo.
"""

from __future__ import annotations

from typing import Any

# Results that are "news" — mirrors scheduler.NOTIFY_RESULTS.
ACTIONABLE_RESULTS = {"found", "proposed", "merged", "escalated", "error"}

# Marker the CI publish step greps for to decide whether to *close* the rolling
# issue (vs. merely edit it to the resolved banner). Kept as an HTML comment so
# it is invisible in the rendered issue.
CLOSE_MARKER = "<!-- loop-report:close -->"

# After this many consecutive clean runs, a previously-published issue is stale
# enough to close outright rather than keep editing.
DEFAULT_CLOSE_AFTER = 7

_BUCKET_ORDER = ("high", "watch", "noise")
_BUCKET_HEADINGS = {
    "high": "High — look at these",
    "watch": "Watch — worth a skim",
    "noise": "Noise — recorded, no action",
}


def is_actionable(section: dict[str, Any]) -> bool:
    """Whether this section's last run produced something a human should see."""
    return section.get("last_result") in ACTIONABLE_RESULTS


def trailing_clean(results: list[str]) -> int:
    """Count consecutive ``clean`` results at the end of a run-log result list."""
    n = 0
    for r in reversed(results):
        if r == "clean":
            n += 1
        else:
            break
    return n


def _escape(text: str) -> str:
    """Neutralize backticks so untrusted commit subjects can't break out of
    inline code spans in the rendered markdown."""
    return text.replace("`", "'")


def render_markdown(loop_id: str, section: dict[str, Any]) -> str:
    """Render one loop's state section as a self-contained markdown report."""
    result = section.get("last_result", "unknown")
    lines = [
        f"# Loop report: `{_escape(loop_id)}`",
        "",
        f"| Phase | Last run (UTC) | Result | Tokens spent |",
        f"|---|---|---|---|",
        f"| {section.get('phase', '?')} | {section.get('last_run', '?')} "
        f"| **{result}** | {section.get('tokens_spent', 0)} |",
        "",
    ]
    note = section.get("note", "")
    if note:
        lines += [f"> {_escape(note)}", ""]

    findings = section.get("findings", [])
    by_bucket: dict[str, list[dict[str, Any]]] = {}
    for f in findings:
        by_bucket.setdefault(f.get("bucket", "watch"), []).append(f)
    for bucket in _BUCKET_ORDER:
        rows = by_bucket.get(bucket)
        if not rows:
            continue
        lines += [f"## {_BUCKET_HEADINGS[bucket]} ({len(rows)})", ""]
        for f in rows:
            lines.append(f"- `{_escape(f.get('sha', '?'))}` {_escape(f.get('text', ''))}")
        lines.append("")

    lines += [
        "---",
        "_Maintained automatically by the daily-triage loop (report-only, L1)._",
        "_Every cited SHA was resolved against the repo by loopguard before this_",
        "_report was written; a run with a fabricated SHA is rejected, not published._",
        "",
    ]
    return "\n".join(lines)


def render_resolved_markdown(
    loop_id: str, section: dict[str, Any], consecutive_clean: int, close_after: int = DEFAULT_CLOSE_AFTER
) -> str:
    """Render the "nothing outstanding" banner for a clean run.

    A rolling issue that only ever gets *edited on findings* becomes a triage
    inbox items can enter but never leave: fifteen clean days later it still reads
    as if last month's findings are live. This banner is the resolution path — a
    clean run overwrites the issue body with an explicit "resolved as of <date>"
    state, and once the clean streak crosses ``close_after`` the issue is stale
    enough to close (signalled by an invisible marker the CI step greps for)."""
    last_run = section.get("last_run", "?")
    phase = section.get("phase", "?")
    should_close = consecutive_clean >= close_after
    lines = [
        f"# Loop report: `{_escape(loop_id)}`",
        "",
        "## ✅ Resolved — nothing outstanding",
        "",
        f"The last **{consecutive_clean}** run(s) were clean; no new commits need triage.",
        f"Previously reported findings are considered resolved.",
        "",
        f"| Phase | Last run (UTC) | Consecutive clean runs |",
        f"|---|---|---|",
        f"| {phase} | {last_run} | {consecutive_clean} |",
        "",
        "---",
        "_Maintained automatically by the daily-triage loop (report-only, L1)._",
        "_A future run that surfaces something will replace this banner with the findings._",
        "",
    ]
    if should_close:
        lines.append(CLOSE_MARKER)
        lines.append("")
    return "\n".join(lines)
