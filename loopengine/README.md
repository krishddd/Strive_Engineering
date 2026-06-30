# loopengine

The Python loop-engineering runtime for [Strive Engineering](../README.md).

It drives the loop cycle — **trigger → gather → verify → state → escalate** — and
delegates the constraint-critical work (command guard, budget brakes, grounded and
isomorphic verification, diff-integrity / injection scanning, the L3 allowlist gate)
to the Rust [`loopguard`](../crates/loopguard) core via its JSON CLI. The language
boundary is subprocess + JSON — no FFI, no maturin, no build coupling.

```bash
cargo build --release          # build the loopguard binary first
pip install -e "loopengine[dev]"
loopengine run loops/example-triage.json
```

## Modules

| Module | Responsibility |
|---|---|
| `runtime` | the L1 `git-commit-triage` loop: trigger → gather commits → verify SHAs → write state → escalate |
| `assisted` | the L2/L3 `assisted-fix` loop: worktree-isolated maker → checker (integrity + tests) → propose, or L3 allowlist auto-merge |
| `makers` | the agent step: provider-agnostic maker (Claude / free NVIDIA NIM / any OpenAI-compatible), structured-output JSON |
| `reflexion` | evaluator-optimizer with bounded reflective retry (no blind oscillation) |
| `consistency` | self-consistency majority vote (never let the maker grade itself) |
| `compaction` | context compaction + structured note-taking for long-horizon loops |
| `scheduler` | multi-loop ticks: cadence, priority, triage-inbox, collision guard, anomaly/oscillation halting |
| `authoring` | scaffold (`init`), token-cost estimate (`cost`), and L0→L3 readiness audit (`audit`) for specs |
| `connectors` | guarded MCP connectors + live JSON-RPC transport; every tool return injection-scanned before use |
| `state` | the durable spine: JSON state keyed by loop id + append-only JSONL run log |
| `validate` | JSON-schema validation of a spec before it runs |
| `core` | the thin subprocess wrapper over the `loopguard` CLI |
| `dashboard_api` | read-only HTTP + a pure `route()` for the observability viewer |
| `cli` | the `loopengine` command-line entry point |

## CLI

```
loopengine run <spec>                 run one cycle of a loop spec
loopengine schedule <dir> [--state]   run every due loop once (one tick)
loopengine serve [--state --port]     read-only dashboard + JSON API
loopengine show <state> <loop_id>     print a loop's current state section

loopengine init <id> [--kind --out]   scaffold a schema-valid starter spec
loopengine cost <spec>                estimate per-run / per-day token spend
loopengine audit <spec> [--json]      score readiness across the L0→L3 ladder

loopengine guard "<cmd>"              check a command against the denylist     (exit 2 block)
loopengine verify <repo> <sha>...     grounded SHA verification                (exit 3/4)
loopengine verify-iso <repo> <sha>... isomorphic-perturbation verification     (exit 8 gap)
loopengine scan-diff [file|-]         flag verifier-tampering in a diff        (exit 5)
loopengine scan-injection [file|-]    scan untrusted text for prompt injection (exit 6)
```

## Testing

All tests are deterministic — the clock, runner, transport, and summarizer are
injected; there are no sockets, no network, and no real model key. Tests that need
the `loopguard` binary are skipped if it isn't built.

```bash
pip install -e "loopengine[dev]"
LOOPGUARD_BIN=../target/release/loopguard.exe pytest tests -q   # 68 tests
```

See the [repo root README](../README.md) for the full picture and the research
behind each defence.
