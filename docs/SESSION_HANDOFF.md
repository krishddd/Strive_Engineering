# Session Handoff

A versioned, paste-ready orientation for a fresh session in this repo. Keep it
current when the architecture changes. (Public-safe: contains no private-repo
names, SHAs, or local-only config paths — those stay in gitignored files.)

## What this is

**Strive Engineering** — a loop-engineering runtime (polyglot Rust + Python) that
designs, runs, verifies, and observes autonomous coding-agent *loops*, gated
through phases L0→L3. Thesis: *the engineering resides in the constraints*, so the
safety-critical logic is a tested **Rust** core (`crates/loopguard`) and the
orchestration is **Python** (`loopengine/`). The cross-language boundary is
subprocess + JSON — no FFI, no maturin.

## Architecture

- **`crates/loopguard` (Rust):** `guard` (command denylist), `budget` (token /
  iteration / wall-clock brakes), `verifier` (grounded commit-SHA existence **+
  isomorphic-perturbation verification**), `integrity` (reward-hacking / diff-tamper
  scan), `injection` (prompt-injection scan), `policy` (L3 allowlist auto-merge
  gate). Library + JSON CLI with stable exit codes: **2** block, **3** fabricated,
  **4** unverifiable→escalate, **5** tamper, **6** injection, **7** allowlist→escalate,
  **8** isomorphic gap.
- **`loopengine/loopengine/` (Python):** `runtime` (L1 `git-commit-triage`),
  `assisted` (L2 propose / L3 allowlist auto-merge via fast-forward, worktree-isolated),
  `makers` (provider-agnostic agent: Claude + free NVIDIA NIM / any OpenAI-compatible,
  stdlib-only HTTP, structured-output JSON), `worktree`, `consistency` (majority vote),
  `reflexion` (evaluator-optimizer retry), `compaction` (context compaction + structured
  note-taking), `connectors` (`GuardedConnector` + live `HttpMCPTransport`; every tool
  return injection-scanned), `scheduler` (multi-loop ticks: cadence / priority /
  triage-inbox / collision guard / **anomaly halting**), `authoring` (`init` / `cost` /
  `audit`), `dashboard_api`, `validate`, `core`, `state`, `cli`.
- **Also:** `schemas/loop.schema.json`, `loops/*.json` examples, `dashboard/index.html`,
  `docs/` (concepts, research-arxiv, safety, failure-modes), `.github/workflows/ci.yml`.

## Build & test (Git Bash / MINGW64)

```bash
export PATH="$HOME/.cargo/bin:$PATH"
cargo test && cargo fmt --all -- --check && cargo clippy --all-targets -- -D warnings
cargo build --release            # produces target/release/loopguard(.exe)

export PYTHONPATH="loopengine"
export LOOPGUARD_BIN="$(pwd)/target/release/loopguard.exe"
python -m pytest loopengine/tests -q
```

Current: **34 Rust + 68 Python = 102 tests** green, fmt + clippy clean.

## Hard-won gotchas

1. **Rust toolchain is windows-gnu with no dlltool/gcc.** Keep deps pure-Rust
   (serde, serde_json, regex). Do **not** add `clap` or anything pulling
   `windows-sys` — it fails with `dlltool not found`. CLI arg-parsing is
   hand-rolled on purpose. `rustup component add rustfmt clippy` is needed.
2. **Tests are deterministic** — inject the clock / runner / transport /
   summarizer / fake-LLM-client. No sockets, no network, no real model key. Tests
   needing the binary are skipped if it isn't built. Keep new tests this way.
3. **Free models:** NVIDIA NIM (free, OpenAI-compatible at
   `https://integrate.api.nvidia.com/v1`, key prefix `nvapi-`, env `NVIDIA_API_KEY`).
   Maker config `{"type":"nvidia","model":"meta/llama-3.3-70b-instruct"}` (default;
   `qwen/qwen3-coder-480b-a35b-instruct` for code, `deepseek-ai/deepseek-r1` for
   reasoning). Claude maker is `{"type":"llm","model":"claude-opus-4-8"}`.
4. **Windows console encoding:** the CLI reconfigures stdout to UTF-8 so glyphs in
   the schedule output don't crash a cp1252 terminal.

## Optional next

Package the CLI for distribution (pip/npm); more loop kinds; richer dashboard
(token/cost/latency panels). Nothing is pending or broken.
