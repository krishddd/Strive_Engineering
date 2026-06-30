# Research Notes

Condensed reference for the concepts this project is built on. Read Tier 1
before designing anything; treat the rest as lookup material per primitive.
This is a fast-moving practitioner space (the term itself is only weeks old
as of this writing) — favor primary sources over secondhand summaries, and
re-check anything tool-specific against current docs before relying on it.

## The mental model

```
Prompt  → one instruction, one turn
Context → what surrounds that instruction
Harness → the environment one agent runs inside for one task
Loop    → the system that triggers, repeats, verifies, remembers
```

A loop is not just "a cron job that calls an LLM." It needs a trigger, a
verifier, external state, and a stop/escalate rule. Missing any one of those,
it's a harness wearing a loop's name.

## Tier 1 — Canonical sources (read first)

- **Addy Osmani — "Loop Engineering"** (the origin essay). Names the five
  building blocks + external state. Introduces "comprehension debt": the
  faster a working loop ships code, the wider the gap between what's in the
  repo and what you actually understand.
- **At least one dissenting take.** There's already pushback clarifying what
  native scheduling/goal commands actually do versus the hype around "prompts
  are dead." Read it before committing architecture to the hype version.
- **Peter Steinberger's and Boris Cherny's original quotes**, in context —
  not just the excerpted lines. They're the "why this matters," not the how.

## Tier 2 — The five building blocks + memory

Research each as its own topic, not just as a row in a table:

- **Automations/Scheduling** — cron-style vs. event-driven triggers; the
  "triage inbox" pattern where empty runs self-archive.
- **Worktrees** — `git worktree` mechanics specifically. A separate working
  directory on its own branch sharing repo history, so two agents' edits
  can't collide. This is the single highest-leverage primitive to understand
  before running more than one agent at a time.
- **Skills** — inline, on-demand project knowledge. Runs in the current
  context window, no new process spawned.
- **Plugins/Connectors (MCP)** — the Model Context Protocol: server/client/
  tool definitions, auth scoping. A read-only connector and a write-scoped
  one are different risk classes — treat them that way in `safety.md`.
- **Sub-agents** — orchestrator-workers pattern: a central agent decomposes
  work, delegates to workers each with a fresh context window, synthesizes
  results.
- **Memory/State** — external state design (a file, DB, or ticket board)
  that survives between runs.

## Tier 3 — Underlying agent architecture patterns

- **ReAct** (reason → act → observe → repeat) — the loop inside almost every
  coding agent today, one level below "loop engineering."
- **Reflexion** — an agent critiques its own prior attempt and retries with
  that feedback folded in.
- **Evaluator-Optimizer / Orchestrator-Workers** (Anthropic's named
  patterns) — one agent generates, another grades; one agent splits work
  across many.
- **Context compaction/compression** — without it, a long-running loop
  overflows its context window. This is "context engineering" living inside
  loop engineering.

Primary sources: Anthropic's "Building Effective Agents" and "Effective
Context Engineering for AI Agents" engineering posts; Yao et al. (ReAct);
Shinn et al. (Reflexion).

## Tier 4 — Operating & safety

- **The three debts**: verification debt (reported done, never independently
  checked), comprehension debt (shipped faster than understood), cognitive
  surrender (accepted uncritically because the system was right before).
- **Failure modes** — see `docs/failure-modes.md` in this repo; add to it
  every time something actually breaks.
- **Cost control** — cost scales with sub-agent fan-out and loop frequency
  far faster than intuition suggests. Budget caps belong in config, not in
  prose.
- **Human-gate design** — what's safe to auto-act on vs. what must escalate;
  see `docs/safety.md`.

## Tier 5 — Tool-specific primitives

If building on Claude Code: read the actual current docs for Hooks,
Subagents, and Skills before wiring any of them — names overlap with the
general concepts above but have specific mechanics (hook types: command,
HTTP, prompt, agent; lifecycle events like `PreToolUse`/`PostToolUse`/`Stop`).
Don't rely on memory here; these surfaces change. If building on another
tool, find its equivalent for each of the five blocks and record the mapping
in `docs/primitives-matrix.md`.

## Tier 6 — Latest developments (2026), and how we responded

This space moves fast; re-check before relying on any of it. As of this repo's
last research pass:

- **Context engineering is now its own discipline.** Anthropic's *Effective
  Context Engineering for AI Agents* and the compaction API (beta header
  `compact-2026-01-12`, with `pause_after_compaction`) make "what the agent
  knows at the moment of action" a first-class concern. The named levers —
  compaction, structured note-taking, sub-agent isolation, just-in-time tool
  calling — are what keep a long-horizon loop from overflowing. → We built
  `loopengine.compaction` (`Compactor` + `Notebook`).
- **Deterministic orchestration is the validated pattern.** Anthropic's Dynamic
  Workflows (May 2026, with Opus 4.8) put the loop/branch/verify logic in a
  *script* — orchestration state lives in variables, not the model's working
  memory, spending zero tokens on coordination. This is the same thesis as our
  Python-deterministic `scheduler` and the Rust constraints core: keep the
  control system out of the model.
- **Reward-hacking research sharpened.** Beyond "agents delete the failing test"
  (which we already scan for), the 2026 result is that *extensional* verification
  induces hacking while *isomorphic* verification prevents it (arXiv:2604.15149),
  with contrastive detection (arXiv:2601.20103) and benchmark-auditing
  (BenchJack, arXiv:2605.12673) as corroboration. → We built `verify-iso`.
- **Agent observability + cost tooling matured** (loop/anomaly detection, token/
  cost/latency/tool-failure gates; readiness-audit and cost-estimate CLIs in the
  wider loop-engineering ecosystem). → We built the scheduler anomaly guard and
  the `audit` / `cost` CLI verbs.

## Open research questions for this project

- Which connector(s) does our first real pattern actually need, and what's
  the minimum viable scope for each?
- What's our actual budget ceiling (token spend we're comfortable with per
  day/week) before we design any L2+ pattern?
