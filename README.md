# Strive Engineering — a loop-engineering runtime

A polyglot toolkit that agents (and humans) use to **do loop engineering**:
design, run, verify, and observe autonomous agent *loops* on a cadence — with the
constraint-critical machinery built in a tested **Rust** core and the orchestration
in **Python**.

> Loop engineering is replacing yourself as the person who prompts the agent — you
> build the system that does it instead. A loop earns its name only if it has a
> **trigger**, a **verifier**, **external state**, and a **stop/escalate** rule.
> Missing any one, it's just a harness. See [`CLAUDE.md`](CLAUDE.md) and
> [`docs/`](docs/) for the full model and the research it's built on.

## Why Rust *and* Python

The research is blunt: *"the code is written by the loop, but the engineering
resides entirely in the constraints."* So the constraints live in Rust, where they
can be deterministic and tested; the orchestration lives in Python, where iteration
is fast.

| Layer | Language | What it owns |
|---|---|---|
| **`loopguard`** (`crates/loopguard`) | **Rust** | Deterministic **command guard** (denylist), hard **budget/iteration/wall-clock brakes**, **grounded verification** primitives. A lib + a JSON-emitting CLI. Fully unit-tested. |
| **`loopengine`** (`loopengine/`) | **Python** | The **runtime**: trigger → gather → verify → state → escalate; scheduler/cadence; external JSON state + run log; maker/checker; CLI. Calls `loopguard`. |
| **schemas** (`schemas/`) | **JSON Schema** | The `loop.json` contract every loop is validated against. |
| **dashboard** (`dashboard/`) | **HTML/JS** | Read-only observability: state, run log, findings, budget. |

Integration across the language boundary is by subprocess + JSON (the runtime calls
the `loopguard` binary), so there's no FFI/linking step to build.

## The six primitives → where they live

| Primitive | In this repo |
|---|---|
| Automations / scheduling | `loopengine.scheduler` (cadence) + the loop `cadence` field |
| Worktrees (isolation) | planned adapter for L2 maker/checker (`docs/`) |
| Skills (codified knowledge) | loop specs + `docs/` patterns |
| Connectors (MCP) | planned; read-only `git` today, no write scope |
| Sub-agents (maker/checker) | runtime verify step; adversarial checker spec in `docs/` |
| Memory / external state | `loopengine.state` (JSON state + JSONL run log) |

## Quick start

```bash
# 1. Build the Rust constraints core (produces target/release/loopguard)
cargo build --release

# 2. Install the Python runtime
pip install -e loopengine

# 3. Try the constraints core directly
loopengine guard "git push --force origin main"     # -> BLOCK (exit 2)
loopengine guard "git log -5"                        # -> allow
loopengine verify /path/to/repo <real-sha> <fake>    # -> grounded vs fabricated

# 4. Run a loop (report-only). Copy loops/example-triage.json, point it at a
#    real repo, then:
loopengine run loops/example-triage.json
loopengine show .loop-state/state.json example-triage
```

## Build phases (gate before advancing)

`L0` manual → `L1` report-only → `L2` assisted PRs (verifier + worktrees) →
`L3` unattended (tight allowlist). Default posture: **start at L1, stay until
boring.** The runtime ships at L1: read-only, single-pass, report-only.

## Status

- ✅ Rust `loopguard`: guard + budget + verifier, 13 unit tests green.
- ✅ Python `loopengine`: runtime, state, CLI, git-commit-triage loop.
- ✅ JSON schema + example loop + CI (Rust + Python).
- 🚧 Dashboard: minimal viewer. L2 maker/checker + worktrees: specced, not wired.

## License

[MIT](LICENSE)
