# loopengine

The Python loop-engineering runtime for [Strive Engineering](../README.md).

Drives the loop cycle — **trigger → gather → verify → state → escalate** — and
delegates the constraint-critical work (command guard, budget brakes, grounded
verification) to the Rust [`loopguard`](../crates/loopguard) core via its CLI.

```bash
cargo build --release          # build the loopguard binary first
pip install -e "loopengine[dev]"
loopengine run loops/example-triage.json
```

See the repo root README for the full picture.
