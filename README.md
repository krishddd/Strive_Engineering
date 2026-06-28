<div align="center">

# Strive Engineering

**A loop-engineering runtime — the system that prompts your agents, so you don't have to.**

A polyglot toolkit for designing, running, verifying, and observing autonomous
agent *loops* — with the constraint-critical machinery in a tested **Rust** core
and the orchestration in **Python**.

[![ci](https://github.com/krishddd/Strive_Engineering/actions/workflows/ci.yml/badge.svg)](https://github.com/krishddd/Strive_Engineering/actions/workflows/ci.yml)
[![license: MIT](https://img.shields.io/badge/license-MIT-blue.svg)](LICENSE)
![rust](https://img.shields.io/badge/rust-loopguard-orange?logo=rust)
![python](https://img.shields.io/badge/python-3.10%2B-3776AB?logo=python&logoColor=white)
![phase](https://img.shields.io/badge/phase-L1%20report--only-23863633)
![status](https://img.shields.io/badge/status-active-brightgreen)

</div>

---

## What is this?

**Loop engineering is replacing yourself as the person who prompts the agent — you
build the system that does it instead.** A loop earns its name only if it has all
four of these; missing any one, it's just a *harness*:

| | |
|---|---|
| 🫀 **Trigger** | a cadence or event wakes the loop |
| ✅ **Verifier** | an external, ungameable check proves the work — not the agent's own word |
| 🧠 **External state** | durable memory that survives between runs |
| 🛑 **Stop / escalate** | it knows when to quit or hand off to a human |

Strive Engineering gives you all four as reusable infrastructure, plus the hard
brakes and safety guards that make an *unattended* loop trustworthy. The first
built-in loop, `git-commit-triage`, watches a repo's commits read-only and writes
a prioritized, **source-cited** report — changing nothing.

## Why Rust *and* Python

The research that drives this repo is blunt: *"the code is written by the loop, but
the engineering resides entirely in the constraints."* So the constraints live in
**Rust**, where they can be deterministic and exhaustively tested; the orchestration
lives in **Python**, where iteration is fast.

```mermaid
flowchart LR
    subgraph PY["loopengine · Python"]
        T[trigger] --> G[gather] --> V[verify] --> S[state] --> E{escalate?}
    end
    subgraph RS["loopguard · Rust core"]
        GUARD[command guard]
        BUDGET[budget brakes]
        VERIFY[grounded verifier]
    end
    G -. shell actions .-> GUARD
    V -. cited SHAs .-> VERIFY
    T -. caps .-> BUDGET
    S --> JSON[(JSON state +<br/>JSONL run log)]
    E -->|risky / fatal| HUMAN[human]
    E -->|clean / found| T
```

The language boundary is **subprocess + JSON** (Python calls the `loopguard`
binary) — no FFI or maturin build step.

| Component | Language | Owns |
|---|---|---|
| [`crates/loopguard`](crates/loopguard) | **Rust** | Deterministic **command guard** (denylist), hard **budget / iteration / wall-clock brakes**, **grounded verification** (commit-SHA existence), a **reward-hacking / diff-integrity scanner**, and a **prompt-injection scanner**. Library + JSON CLI. |
| [`loopengine/`](loopengine) | **Python** | The **runtime**: trigger → gather → verify → state → escalate; **self-consistency voting**, **Reflexion-style retry**, JSON-schema-validated specs, external state + run log; CLI. |
| [`schemas/`](schemas) | **JSON Schema** | The `loop.json` contract every loop is validated against. |
| [`dashboard/`](dashboard) | **HTML/JS** | Read-only observability: state, findings, run log, budget. |

## The verifier is the whole game

A loop iterates *until a check passes*, which makes it a **Goodhart amplifier**: any
gap between "passes the check" and "is actually correct" gets brute-forced into an
exploit (tell it "make tests pass" with an exit-code check and it learns to delete
the failing test). The defence is a verifier the optimizer *cannot game*.

Here, every reported finding cites a commit SHA, and `loopguard` confirms each one
resolves in the target repo (`git cat-file -e`). A SHA either exists or it doesn't —
there is nothing to talk past. A finding with an unresolvable SHA makes the **whole
run invalid**, not merely flagged. See [docs/](docs/) for the full critique.

### Hardened against the ways loops actually cheat (research-driven)

The defences below each implement a specific result from the literature — full
annotated bibliography in [`docs/research-arxiv.md`](docs/research-arxiv.md):

| Threat | Defence | Source |
|---|---|---|
| Agent passes a check by **deleting the test / weakening the assertion / editing the eval harness** | `loopguard scan-diff` flags removed tests, added skip markers, removed assertions, and edits to test/eval/CI files → auto-escalate | Reward Hacking Benchmark (2605.02964); RLVR verifier gaming (2604.15149) |
| **Indirect prompt injection** via ingested tool returns | `loopguard scan-injection` scores instruction-override / role-spoof / exfiltration before the loop acts (verify-before-commit) | Task Shield (2412.16682); IPIGuard (2508.15310); VIGIL (2601.05755) |
| **LLM-judge is inconsistent / self-preferring** | never let the maker grade itself; `majority_vote` requires consensus across N independent verdicts and escalates on disagreement | Rating Roulette (2510.27106); Reliability without Validity (2606.19544) |
| **Blind retry oscillates** | `run_reflexion` feeds the checker's reason-for-failure into the next attempt, bounded by the iteration cap | Reflexion (2303.11366); Self-Refine (2303.17651) |

## The six primitives → where they live

| Primitive | In this repo |
|---|---|
| Automations / scheduling | loop `cadence` + the runtime's single-pass trigger |
| Worktrees (isolation) | `loopengine.worktree` — every assisted-fix attempt runs in an isolated worktree |
| Skills (codified knowledge) | loop specs + `docs/` patterns |
| Connectors (MCP) | `loopengine.connectors` — every tool return is injection-scanned before the loop acts (read-only by default) |
| Sub-agents (maker/checker) | the **assisted-fix** loop: maker proposes, checker (integrity + tests) verifies |
| Memory / external state | `loopengine.state` — JSON state + JSONL run log |

## Quick start

```bash
# 1. Build the Rust constraints core → target/release/loopguard
cargo build --release

# 2. Install the Python runtime
pip install -e "loopengine[dev]"

# 3. Poke the constraints core directly
loopengine guard "git push --force origin main"   # → BLOCK (exit 2)
loopengine guard "git log -5"                      # → allow
loopengine verify /path/to/repo <real-sha> <fake>  # → grounded vs fabricated
git diff | loopengine scan-diff -                   # → flags test-deletion (exit 5)
loopengine scan-injection suspicious.txt            # → flags prompt injection (exit 6)

# 4. Run a loop (report-only). Copy the example, point it at a real repo:
cp loops/example-triage.json loops/local-mine.json   # edit target.repo
loopengine run loops/local-mine.json
loopengine show .loop-state/state.json example-triage
```

Open [`dashboard/index.html`](dashboard/index.html) in a browser and drop your
`.loop-state/state.json` onto it to see findings and run history.

## Project layout

```
Strive_Engineering/
├── crates/loopguard/      # Rust: guard + budget + verifier (lib + CLI), 13 tests
├── loopengine/            # Python: runtime, state, CLI, git-commit-triage, 5 tests
├── schemas/               # JSON Schema for a loop spec
├── loops/                 # example loop definitions (real targets stay gitignored)
├── dashboard/             # HTML/JS observability viewer
├── docs/                  # concepts, verification critique, safety, failure modes
└── .github/workflows/     # CI: fmt + clippy + cargo test + pytest
```

## The assisted-fix loop (L2)

`assisted-fix` is the maker/checker loop, end to end:

```
worktree off base_ref → maker proposes an edit → checker gates it:
   1. integrity scan of the diff   (deleted test / weakened assertion → ESCALATE, no retry)
   2. injection scan of the task   (prompt injection in the brief → ESCALATE)
   3. run test_command in worktree  (the ground-truth verifier)
→ on test failure: Reflexion feeds the reason into the next attempt (bounded by the cap)
→ on success: commit to a branch and leave it for a human — it never auto-merges
```

The maker is where the loop **actually prompts an agent**. It's pluggable across
providers:

- `"maker": {"type": "nvidia", "model": "meta/llama-3.3-70b-instruct"}` — a **free**
  model via [NVIDIA NIM](https://build.nvidia.com) (OpenAI-compatible, no card, set
  `NVIDIA_API_KEY`). **No extra dependency** — stdlib HTTP only. See *Free models* below.
- `"maker": {"type": "llm", "model": "claude-opus-4-8"}` — a **Claude-backed
  implementer**. Install `pip install -e "loopengine[llm]"`, set `ANTHROPIC_API_KEY`.
- `"maker": {"type": "openai", "base_url": "...", "model": "...", "api_key_env": "..."}`
  — any OpenAI-compatible endpoint (Groq, OpenRouter, a local NIM container, …).
- `"maker_command": "..."` — a shell command run in the worktree; or inject any
  Python callable programmatically.

### Free models for development (NVIDIA NIM)

NVIDIA's [build.nvidia.com](https://build.nvidia.com) gives free, OpenAI-compatible
API access (~40 req/min, no credit card) to 100+ models. Recommended picks for this
pipeline — switching is a one-line `model` change:

| Use | Model id | Why |
|---|---|---|
| **Assisted-fix maker (default)** | `meta/llama-3.3-70b-instruct` | Reliable JSON / structured output, fast, free |
| **Best code quality** | `qwen/qwen3-coder-480b-a35b-instruct` | Purpose-built for agentic coding |
| **Reasoning-heavy fixes** | `deepseek-ai/deepseek-r1` | Strong reasoning (the maker strips its `<think>` blocks) |
| **Cheap/fast side tasks** | `meta/llama-3.1-8b-instruct` | Lowest latency for light work |

```bash
export NVIDIA_API_KEY=nvapi-...          # free key from build.nvidia.com
loopengine run loops/example-l3-autofix.json   # spec uses {"type":"nvidia",...}
```

The same maker also works with other free OpenAI-compatible tiers (Groq, Google AI
Studio via a proxy, OpenRouter free models) — use `{"type":"openai","base_url":...}`.

Whatever the maker proposes is still gated by the integrity scanner and the test
command — a model that tries to delete the failing test is caught and escalated,
not merged. Blast radius is a throwaway branch in an isolated worktree; `main` is
never touched. See [`loops/example-assisted-fix.json`](loops/example-assisted-fix.json).

### L3 — unattended, allowlist-gated (`assisted-fix` with `phase: "L3"`)

At L3 the loop may act on its own — but only inside a tight allowlist. After the
verifier passes, the diff goes through a deterministic **allowlist gate**
(`loopguard check-allowlist`): it auto-merges into `base_ref` (a fast-forward —
never a force-push) **only if** every file matches an allow glob, none match a
deny glob, it's within the file/line caps, and it's integrity-clean. Anything
else falls back to L2 behavior — propose a branch and escalate. It also refuses to
move `base_ref` if that branch is checked out in the target. Default deny list
covers `auth/`, `payments/`, `secrets/`, `migrations/`, CI workflows, and more.

### Connectors (MCP) — reach out, but verify first

`loopengine.connectors.GuardedConnector` wraps any MCP transport so **every tool
return is run through the injection scanner before the loop can act on it**
(verify-before-commit). Connectors are read-only by default; write tools require
explicit, L3-only scope. The transport is injected, so there is no path to act on
an unscanned result.

## Build phases — gate before advancing

`L0` manual → **`L1` report-only** (`git-commit-triage`) → **`L2` assisted PRs**
(`assisted-fix`: verifier + worktrees, propose-only) → **`L3` unattended**
(`assisted-fix` + allowlist auto-merge). Default posture: **start at L1, stay
until boring.**

## Develop & test

```bash
cargo test                       # Rust unit tests (13)
cargo clippy --all-targets -- -D warnings
pip install -e "loopengine[dev]" && pytest loopengine/tests -q   # Python (5)
```

CI runs all of the above on every push, plus a manual-dispatch report-only
self-triage job.

## Status

- ✅ Rust `loopguard`: guard + budget + verifier + diff-integrity + injection scanners +
  **L3 allowlist policy gate** — **29 unit tests**, fmt + clippy clean.
- ✅ Python `loopengine`: runtime, state, CLI, self-consistency, Reflexion, schema
  validation, worktree isolation, the **`assisted-fix` loop (L2 propose / L3 auto-merge)**,
  a **Claude-backed agent maker**, and **guarded MCP connectors** — **31 tests**; end-to-end
  coverage of triage, escalation, the research features, assisted-fix, the LLM maker, L3
  auto-merge (allowlisted / escalated), and connector injection-blocking.
- ✅ JSON schema (per-kind conditional validation), example loops, dashboard, CI,
  [arXiv bibliography](docs/research-arxiv.md).
- 🚧 Planned: richer dashboard + JSON HTTP API; a live MCP transport binding; multi-loop scheduler.

## License

[MIT](LICENSE) © krishddd
