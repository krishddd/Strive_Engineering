# Loop Engineering — Project CLAUDE.md

This file loads at the start of every Claude Code session in this repo. It is the
single source of truth for what this project is, what we're building, how we
build it, and what's off-limits. Keep it accurate — when a decision changes,
edit this file in the same session, don't let it drift.

> **Assumption stated up front:** this is a from-scratch, personally-built
> loop-engineering practice — not a clone of any existing repo. Adjust names,
> scope, and the pattern backlog below to match your actual goals as you go.

**Files already scaffolded — read on demand, not all at once:**

| File | When to open it |
|---|---|
| `.loop-state/state.json` | Machine state — current status per loop, keyed by id (the runtime's spine). Gitignored on `main`; its durable home is the `loop-state` branch. |
| `.loop-state/state.runlog.jsonl` | Append-only run log (one JSON row per run) — the audit trail. |
| `docs/conventions/STATE.md` | The human-readable STATE convention (the machine spine above is the source of truth). |
| `docs/conventions/RUNLOG.md` | The human-readable RUNLOG convention. |
| `loops/*.json` | One JSON spec per loop pattern (schema-validated) — this is where a pattern's trigger/verifier/state/budget live. |
| `docs/research-notes.md` | Before designing a new pattern or primitive |
| `docs/failure-modes.md` | Before raising a pattern's phase; append after any real incident |
| `docs/safety.md` | Before wiring any connector, hook, or write action |
| `docs/primitives-matrix.md` | Only if porting a pattern to a second tool |
| `.claude/settings.json` | The enforcement layer — PreToolUse hook wiring (see §8). |
| `docs/SESSION_HANDOFF.md` | Fast orientation for a fresh session — architecture, build/test, gotchas |

---

## 1. What This Project Is

We are building our own small system of **agent loops** — recursive,
goal-driven automations that run a coding agent on a cadence, verify what it
did, write the result to durable state, and either act, hold for a human, or
loop again. The point is not one clever prompt. The point is a control system
around the agent that we can trust to run without us watching every turn.

**Primary build target:** Claude Code (hooks, subagents, skills, `/loop`,
worktrees). If a pattern is later ported to another tool (Codex, GitHub
Actions), document the mapping in `docs/primitives-matrix.md`.

**Non-goals:** this is not a framework for other people yet. Don't generalize
prematurely — build the loop that solves a real recurring task we actually
have, get it boring and reliable, then generalize.

---

## 2. The Mental Model (read this before designing anything)

```
Prompt        → one instruction, one turn
Context       → what surrounds that instruction (files, history, retrieved data)
Harness       → the environment one agent runs inside for one task
Loop          → the system that triggers, repeats, verifies, and remembers
                 across many runs of the harness
```

A loop earns its name only if it has: a **trigger** (schedule or event), a
**verifier** (proof of done, not a self-report), **external state** (memory
outside the conversation), and a **stop/escalate rule** (it must know when to
quit or hand off, not run forever).

If a "loop" you're designing is missing any of those four, it's still a
harness — fine to build, just don't call it done.

---

## 3. The Five Building Blocks + Memory

Every pattern we build should be describable in terms of these. If you can't
name the worktree story or the state file for a pattern, it isn't ready to
automate.

| Primitive | Job | Claude Code mechanism |
|---|---|---|
| **Automations / Scheduling** | Discovery + triage on a cadence | `/loop`, cron-style scheduled tasks |
| **Worktrees** | Safe parallel execution, no file collisions | `git worktree`, `--worktree` flag, `isolation: worktree` on subagents |
| **Skills** | Persistent, reusable project knowledge | `SKILL.md` in `.claude/skills/<name>/` — runs inline in current context |
| **Plugins / Connectors** | Reach into real tools (tickets, CI, chat) | MCP servers |
| **Sub-agents** | Maker / checker split, isolated context | `.claude/agents/<name>.md` — own context window, returns a summary |
| **+ Memory / State** | Durable spine outside any conversation | `STATE.md` / `RUNLOG.md` (see §6) |

**Skill vs. subagent, decided once and for all:** a skill runs inline in the
main thread — use it when you want to see and steer each step. A subagent
spawns an isolated context — use it when the side task (log scan, dependency
audit, deep search) would otherwise clutter the main conversation with
intermediate output you'll never reference again.

**Hooks are the enforcement layer, not the design layer.** CLAUDE.md
instructions are advisory — Claude follows them most of the time, not every
time. Anything that must hold 100% of the time (no force-push, no `rm -rf`,
must run tests after an edit) belongs in a hook (`PreToolUse`, `PostToolUse`,
etc. in `.claude/settings.json`), not in prose here.

---

## 4. Target Repo Structure

```
/
├── CLAUDE.md                 # this file
├── crates/loopguard/         # Rust constraints core (guard/budget/verifier/…)
├── loopengine/               # Python runtime, CLI, tests
├── loops/*.json              # one JSON spec per loop pattern (schema-validated) — §7
├── schemas/loop.schema.json  # the loop-spec contract
├── .loop-state/              # machine state + run log (gitignored on main;
│                             #   durable home is the loop-state branch)
├── .claude/
│   └── settings.json         # the enforcement layer — PreToolUse hooks (§8)
├── scripts/                  # helper/verifier scripts a hook calls
│   └── hooks/guard_bash.py   #   the interactive-session safety guard
├── docs/
│   ├── conventions/          # human-readable STATE.md / RUNLOG.md conventions
│   ├── primitives-matrix.md  # tool-to-primitive mapping if multi-tool
│   ├── failure-modes.md      # incident log, append as things break
│   ├── safety.md             # expanded version of §8
│   └── research-notes.md     # condensed reading list, sources, decisions
└── .github/workflows/ci.yml  # tests + the closed daily-triage loop
```

The durable state is the JSON spine (`.loop-state/`), not root-level Markdown;
the Markdown under `docs/conventions/` documents the convention. Create a folder
when the first thing that needs it exists, not before.

---

## 5. Build Phases (gate before moving forward, don't skip a phase)

| Phase | What it means | Exit criteria |
|---|---|---|
| **L0 — Manual** | Run the workflow by hand, no automation | You've done it manually at least 3 times and can write the steps down exactly |
| **L1 — Report-only** | Loop runs on a cadence, writes findings to STATE.md / opens an issue, **makes zero changes** | A week of runs with no false alarms and no missed real issues |
| **L2 — Assisted fixes** | Loop proposes a patch (PR, not a direct commit) for a narrow, allow-listed class of change | Every L2 PR in the trial period needed zero or trivial human edits |
| **L3 — Unattended** | Loop can commit/merge/act without a human in the loop, within a tightly scoped allowlist | Only after L2 has run clean for a meaningful stretch, and only for the most boring, lowest-blast-radius pattern first |

Default posture for a new pattern: **start at L1, stay there until bored.**
Boredom (it never finds anything wrong, or it's always right) is the signal
to advance — not impatience.

---

## 6. Memory / State Conventions

- `.loop-state/state.json` holds **current status only** — one section per loop
  keyed by id, overwritten each run. This is what a loop reads at the start of a
  run to know what happened last time. (`docs/conventions/STATE.md` documents the
  convention; the JSON is the source of truth.)
- `.loop-state/state.runlog.jsonl` is **append-only** — one JSON row per run:
  timestamp, loop, result (found/clean/error/escalated), action taken, counts,
  note. Never edited, only appended. It is the audit trail streaks are read from
  (e.g. "how many consecutive clean runs" drives the rolling-issue resolution).
- Every pattern's spec (in `loops/*.json`) must state explicitly (via its kind +
  target + budget): what it reads from state, what it writes back, and what counts
  as "nothing to do." Non-ASCII in state must survive a round-trip — force UTF-8 on
  every subprocess boundary (see `docs/failure-modes.md`, mojibake incident).
- If a loop can't tell a recoverable error (a failing test — feedback to act
  on) from a fatal one (a missing credential — hard stop), it is not ready to
  run unattended. Fix that before raising its phase.

---

## 7. Pattern Backlog

Add a row when a pattern is identified; fill in cadence/level/status as it
moves through the build phases. The single spec for each pattern is its
`loops/*.json` (trigger, verifier via `kind`, state contract, budget/blast
radius, current phase).

| Pattern | Cadence | Current Phase | Spec |
|---|---|---|---|
| `sec-guardrails-triage` — daily commit triage of the SEC_Guardrails_Agent repo | 1d (manual, local) | L1 — **stalled** (no local trigger; last run 2026-06-25) | `loops/local-sec-guardrails.json` (gitignored — private target) |
| `ci-self-triage` — daily commit triage of this repo, closed loop in Actions (cron → cursors on `loop-state` branch → rolling `loop-report` issue) | 1d (cron 05:23 UTC) | L1 — **healthy** (15+ clean scheduled runs; report-only by nature, so it stays L1) | `loops/ci-self.json` |
| `example-pr-triage` — read-only open-PR triage over the guarded GitHub connector | 1d | L1 (example / not yet scheduled) | `loops/example-pr-triage.json` |

> **`sec-guardrails-triage` is stalled, not retired.** It has a 1d cadence but no
> trigger (the CI loop got a cron; this one never did), so it silently stopped —
> exactly the failure a loop system should make visible. Either give it a local
> trigger (Task Scheduler / `loopengine schedule` on a timer) or mark it `paused`
> in its spec. Don't leave it in the ambiguous middle.

Good first candidates (low blast radius, easy to verify, classic L1 starts):
daily issue/PR triage, changelog drafting from merged PRs, post-merge cleanup
on a schedule. Avoid CI-sweeping or auto-merge-anything as a first pattern —
high token cost and high blast radius for a system you haven't trusted yet.

---

## 8. Safety Rules (non-negotiable — convert each into a hook, don't rely on this prose alone)

- **No destructive git operations** without an explicit human-approved step:
  no force-push, no `rm -rf`, no history rewrite from inside a loop. *Enforced:*
  `.claude/settings.json` wires a PreToolUse hook (`scripts/hooks/guard_bash.py`)
  that blocks these shapes in interactive sessions; the Rust `loopguard` denylist
  covers loop-spawned commands.
- **No write-scope MCP/connector calls** (ticket close, message send, deploy)
  from an L1 or L2 pattern. Write scope is an L3-only privilege, and only for
  an allowlisted action set defined in `docs/safety.md`.
- **Every loop has a budget cap** (max tokens or max runs per day) enforced
  in the automation config, not just documented.
- **Every loop has an escalation path.** If it's stuck, confused, or hits
  something outside its allowlist, it stops and writes a clear note to
  STATE.md for a human — it does not retry indefinitely and does not guess.
- **One verifier per claim of "done."** A loop reporting success on its own
  word is not verification. Tests passing, a diff existing, a status code —
  something external and checkable.
- **Track the three debts honestly, in `docs/failure-modes.md`:**
  - *Verification debt* — did we actually check, or trust the self-report?
  - *Comprehension debt* — do we still understand what shipped, or just that something shipped?
  - *Cognitive surrender* — are we accepting outputs uncritically because the system has been right before?

---

## 9. Research References (condensed — full notes in `docs/research-notes.md`)

- Addy Osmani — *Loop Engineering* (origin essay; five primitives + memory, comprehension debt)
- Anthropic — *Building Effective Agents* (orchestrator-workers, evaluator-optimizer patterns)
- Anthropic — *Effective Context Engineering for AI Agents* (why long loops overflow context and how to prune/compact)
- ReAct (Yao et al.) and Reflexion (Shinn et al.) — the reasoning loops under every pattern here
- Claude Code docs — Hooks reference, Subagents, Skills (read the actual docs, not summaries, before wiring any of these)
- Model Context Protocol spec — before adding any connector with write access

---

## 10. Definition of Done, per pattern

A pattern is not "done," it's at a phase. Before calling any phase complete:

- [ ] Spec file exists in `patterns/` with trigger, verifier, state contract, blast radius
- [ ] Ran manually (L0) and the steps are written down
- [ ] State read/write contract matches what's actually in STATE.md
- [ ] Budget cap and escalation path are configured, not just described
- [ ] A week (or N runs) of clean operation at current phase before advancing

---

## 11. Session Log (update this every session — newest on top)

> Keep entries short: date, what changed, what's next. This is how a new
> session (or a future you) picks up context fast instead of re-deriving it.

- **2026-08-10** — Pipeline gap sweep. (1) **Enforcement layer now exists**:
  `.claude/settings.json` + `scripts/hooks/guard_bash.py` — a PreToolUse hook that
  blocks force-push / `rm -rf` / history-rewrite in interactive sessions (§8 turned
  from prose into a check; unit-tested). (2) **Clean-run issue hygiene**: a clean
  run now edits the rolling `loop-report` issue to a "resolved — nothing outstanding"
  banner (and closes it after a 7-run clean streak) instead of leaving stale findings
  live — `report.render_resolved_markdown` + `loopengine report --resolved`, wired in
  `ci.yml`. (3) **New loop kind `pr-triage`** — read-only open-PR triage over the
  guarded `GitHubTransport` (the connector was unused by any loop); schema + CLI +
  example + 6 tests. (4) **Mojibake**: logged the 2026-07-06 incident in
  `docs/failure-modes.md`, added idempotent `scripts/scrub_mojibake.py`, scrubbed the
  local state. (5) CLAUDE.md synced to reality (§4/§6/§7 point at `.loop-state/` +
  `loops/*.json`, not root `STATE.md`/`patterns/`); `ci.yml` comment fixed;
  `Swatinem/rust-cache` added to `daily-triage`. Tests **101 → ~113 Python** green.
  Next: give `sec-guardrails-triage` a real local trigger or mark it `paused`;
  optionally schedule `pr-triage` in CI (read-only token).
- **2026-07-06** — Closed the loop on GitHub. (1) UTF-8 forced on every
  subprocess boundary (Windows cp1252 was writing mojibake into STATE findings;
  regression test added). (2) CI `daily-triage` is now a real L1 loop: daily
  cron, cursors persisted on a dedicated `loop-state` branch, actionable
  findings published to a rolling `loop-report` issue via the new
  `loopengine report` command (exits 1 on clean — nothing published). (3) New
  `loopengine.proposer` — the one sanctioned L2 write (documented in
  `docs/safety.md`): pushes only `loop/*` branches, never force, opens a PR
  whose body carries the verifier evidence; wired via the spec's `proposer`
  block. (4) Read-only `GitHubTransport` behind `GuardedConnector` (structurally
  GET-only; issue/PR bodies injection-scanned). Tests **102 → 120** (34 Rust +
  86 Python). Next: first PR-triage loop on the GitHub connector; verify the
  scheduled CI run end-to-end after push.
- **2026-06-30** — Pipeline upgrade to the 2026 research frontier. Added: Rust
  **isomorphic-perturbation verifier** (`verify-iso`, exit 8 — extensional vs
  isomorphic verification, arXiv:2604.15149); Python **context compaction +
  structured note-taking** (`loopengine.compaction`, per Anthropic context
  engineering); **scheduler anomaly/oscillation halting**; **spec authoring CLI**
  (`init` / `cost` / `audit`). Docs/READMEs expanded, arXiv bibliography refreshed
  (+§5–7), sanitized `docs/SESSION_HANDOFF.md` added. Tests **75 → 102** (34 Rust
  + 68 Python), fmt + clippy clean. Next: optional CLI packaging; richer dashboard.
- **YYYY-MM-DD** — Project scaffolded. CLAUDE.md created. No patterns built yet. Next: pick the first real recurring task and write its spec in `patterns/`.

---

## 12. Open Questions

- Which is the actual first recurring task worth automating? (Don't invent one — pick a real one you already do by hand.)
- Single-repo or multi-repo scope for v1?
- Which connectors (if any) does the first pattern actually need, and what's their access scope?
