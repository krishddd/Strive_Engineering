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

_BUCKET_ORDER = ("high", "watch", "noise")
_BUCKET_HEADINGS = {
    "high": "High — look at these",
    "watch": "Watch — worth a skim",
    "noise": "Noise — recorded, no action",
}


def is_actionable(section: dict[str, Any]) -> bool:
    """Whether this section's last run produced something a human should see."""
    return section.get("last_result") in ACTIONABLE_RESULTS


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
