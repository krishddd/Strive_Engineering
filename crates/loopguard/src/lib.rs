//! # loopguard
//!
//! The **constraints core** of the loop-engineering runtime. The runtime's value
//! is not that it can call an LLM in a loop — that part is trivial. The value is
//! in the constraints that make an *unattended* loop safe: a deterministic
//! command guard, hard budget/iteration/wall-clock brakes, and grounded
//! verification the loop cannot game. Those are exactly the pieces that must hold
//! 100% of the time, so they live here, in Rust, with tests — not in advisory
//! prose the agent follows only most of the time.
//!
//! The Python runtime (`loopengine`) drives policy and orchestration and calls
//! into this core (today via the `loopguard` CLI, which emits JSON).

pub mod budget;
pub mod guard;
pub mod verifier;

pub use budget::{BrakeReason, Budget, Ledger};
pub use guard::{Decision, Guard};
pub use verifier::{verify_batch, verify_commit_sha, BatchResult, ClaimVerdict, Verdict};
