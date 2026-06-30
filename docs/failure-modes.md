# Failure Modes

Incident-style catalog. Add a new entry every time something actually
breaks in this project — don't wait for a "lessons learned" cleanup pass.
A short, honest entry written the day it happened is worth more than a
polished one written from memory weeks later.

Each entry: **what happened, why, what mitigates it.** Mark whether it's a
known risk we're watching for, or something that actually occurred here
(date it if so).

---

### File collision outside a worktree
Two agents (or an agent and a human) edit the same file at the same time
outside isolated worktrees — same problem as two engineers committing to the
same lines with no communication. **Mitigation:** any pattern running more
than one agent, or any agent running alongside live human edits, gets its
own worktree. No exceptions.

### Self-report verification
A loop marks a task "done" based on the agent's own claim, with no
independent check. Plausible-looking but wrong output ships at scale.
**Mitigation:** every pattern needs an external verifier — a test passing, a
diff existing, a status code — not a self-report.

### Retry-forever on a fatal error
The loop can't distinguish a recoverable error (a failing test — feedback to
act on) from a fatal one (missing credential, broken environment — a hard
stop) and burns budget retrying something that will never succeed.
**Mitigation:** explicit error classification in the pattern spec; fatal
errors escalate immediately, they don't retry.

### Token/cost blowout
Sub-agent fan-out and loop frequency multiply cost faster than intuition
suggests, especially once a pattern is "working" and tempting to run more
often or spawn more helpers. **Mitigation:** hard budget cap per pattern,
enforced in config, checked in `STATE.md` before each run — not just
documented intent.

### Comprehension debt
The loop ships faster than the human understands what shipped. Debt
compounds silently and is hard to measure after the fact. **Mitigation:**
nothing ships from an L2+ pattern without the human actually reading the
diff before/shortly after — speed is not an excuse to stop reading.

### Cognitive surrender
Outputs get accepted uncritically because the system has been right before.
The risk goes up, not down, as a loop earns trust. **Mitigation:** treat a
clean track record as a reason to spot-check occasionally, not a reason to
stop checking.

### Multi-loop collision
Two of our own loops (or a loop and a scheduled CI job) act on the same
resource at overlapping times and step on each other. **Mitigation:**
document cadence and resource ownership per pattern in `patterns/`; check
for overlap before adding a new scheduled loop.

### Silent verifier failure
The verifier itself breaks (script error, expired credential) and the loop
interprets "no result" as "nothing to do," silently skipping real issues.
**Mitigation:** a verifier crashing must produce an `error` result in
`RUNLOG.md`, never a `clean` one — fail loud, not quiet.

### Stale state
`STATE.md` doesn't get updated (or gets updated incorrectly), so the next
run repeats already-done work or misses where it left off. **Mitigation:**
state read/write is part of the pattern's definition of done, not an
afterthought — see the checklist in `CLAUDE.md` §10.

### Context overflow on a long-running loop
A loop that runs many iterations accumulates transcript until it overflows the
context window, or silently drops the early decisions that still matter — and
its cost climbs the whole time. **Mitigation:** `loopengine.compaction` compacts
the transcript over a token threshold (keeping decisions/open bugs, dropping
redundant tool outputs) and `Notebook` keeps durable notes outside the window.
Treat the compaction threshold as part of the budget cap (see `safety.md`).

### Oscillation / no-progress (single-verifier brute force)
A loop flaps between two states (fix A breaks B, fix B breaks A) or keeps hitting
the same wall, re-running and burning budget with nothing to show. **Mitigation:**
the scheduler's anomaly guard detects `stall` (same failing result N times) and
`oscillation` (strict A/B flapping) from the result history and halts the loop
with an escalation note instead of re-running it. *Known risk we now watch for.*

### Reward hacking via a single literal verifier
The agent satisfies the letter of one check without its intent (an ambiguous SHA
prefix, a tag passed off as a commit, a check that's technically green). A lone
extensional verifier is one shortcut waiting to be found. **Mitigation:**
`loopguard verify-iso` checks each claim under an equivalent second predicate and
escalates on any gap — isomorphic verification, not extensional. *Known risk.*

### Scope creep on connector permissions
A connector originally scoped read-only quietly gets write access added to
unblock one task, and the new scope outlives the task. **Mitigation:** scope
changes go through `docs/safety.md` review, not an inline tweak during a
build session.

---

## Log of actual incidents in this project

| Date | Pattern | What happened | Root cause | Fix / mitigation applied |
|---|---|---|---|---|
| _(none yet)_ | | | | |
