# Safety

This is the operational version of `CLAUDE.md` §8. Rules here should be
implemented as hooks/config wherever possible — this document describes what
to enforce; it is not the enforcement itself. If a rule below isn't backed by
an actual hook or config setting yet, treat it as a gap to close, not a rule
already in force.

## Per-phase permission matrix

| Action | L0 (manual) | L1 (report-only) | L2 (assisted) | L3 (unattended) |
|---|---|---|---|---|
| Read repo/files | — | yes | yes | yes |
| Write to STATE.md/RUNLOG.md | — | yes | yes | yes |
| Open an issue | — | yes | yes | yes |
| Open a PR (no auto-merge) | — | no | yes (allowlisted change types only) | yes |
| Commit directly to main | — | no | no | only for the specific allowlisted pattern under explicit review |
| Force-push / history rewrite | — | no | no | no — never automated, ever |
| Merge a PR | — | no | no | only allowlisted patterns, after a clean trial period |
| Call a write-scope connector (close ticket, send message, deploy) | — | no | no | only allowlisted actions, explicitly scoped per connector |
| Delete data/resources | — | no | no | no — requires human action regardless of phase |

Promote a pattern up this table only after it has met the exit criteria in
`CLAUDE.md` §5 — not on a hunch that it's probably fine now.

## Denylist (hook-enforced, not advisory)

These should be blocked by a `PreToolUse` hook, not left to instructions:

- `rm -rf` or equivalent recursive destructive deletes
- `git push --force` / `git push -f` to any shared branch
- Any command that rewrites git history on a branch others may have pulled
- Direct writes to production credentials/secrets files
- Any database write outside an explicitly allow-listed read-only query path

## Connector / MCP scope rules

- Default every new connector to **read-only**. Write scope is a deliberate,
  separate decision — never the default to "get something working."
- Document the scope of every connector in use here, one entry per
  connector: name, scope (read/write), what it's allowed to touch, which
  pattern(s) use it.
- A connector's scope change (read→write) requires updating this file in the
  same session it's changed — not after the fact.

| Connector | Scope | Allowed to touch | Used by pattern(s) |
|---|---|---|---|
| _(none configured yet)_ | | | |

## Budget caps

- Every pattern has a token and/or run-count cap defined in its spec
  (`patterns/<name>.md`) and enforced in the automation config — not just
  written down.
- If a pattern hits its cap mid-run, it stops and writes an `escalated`
  result to `RUNLOG.md`. It does not borrow next period's budget.

## Escalation rule

A loop escalates to a human (writes a clear note to `STATE.md`, stops, does
not retry) when:
- It hits a fatal error (see `failure-modes.md`)
- It's about to take an action outside its allowlisted scope for its current
  phase
- It hits its budget cap
- Its own verifier fails to run (`loopguard` exit 4 — unverifiable)
- A cited claim shows an **isomorphic gap** (`loopguard verify-iso` exit 8): it
  passed one ungameable check but not its equivalent — a verifier shortcut
- The scheduler flags an **anomaly** (`stall` or `oscillation`): the loop is
  stuck or making no progress and must not be re-run blindly

An escalation should always include: what it was trying to do, what stopped
it, and what it needs from a human to proceed.

## loopguard exit-code contract

The Python runtime keys its escalation decisions off these stable exit codes:

| Code | Meaning | Runtime response |
|---|---|---|
| 0 | ok / allow / clean / auto-ok | proceed |
| 2 | command blocked by the denylist | refuse the command |
| 3 | a cited SHA is fabricated | invalidate the run |
| 4 | verifier could not run (unverifiable) | **escalate** — never treat as clean |
| 5 | diff tampers with the verifier (reward hacking) | **escalate**, no retry |
| 6 | high-severity prompt injection in untrusted text | **escalate** before acting |
| 7 | change not auto-mergeable under the L3 allowlist | fall back to L2 propose-only |
| 8 | isomorphic-perturbation gap (verifier shortcut) | **escalate** — invalidate the run |

## Long-running loops — context as a budget

A loop that runs many iterations spends context as surely as it spends tokens.
`loopengine.compaction` makes that a structural brake: once a transcript crosses
its threshold it is compacted (decisions and open items kept, tool outputs
dropped). Treat the compaction threshold as part of a pattern's budget cap, not
a tuning knob — an uncompacted long loop is an unbounded-cost loop.

## Review cadence

- Re-read this file and `failure-modes.md` before promoting any pattern to a
  higher phase.
- Spot-check at least one clean (`result: clean`) run per pattern per week
  even when nothing looks wrong — see "cognitive surrender" in
  `failure-modes.md`.
