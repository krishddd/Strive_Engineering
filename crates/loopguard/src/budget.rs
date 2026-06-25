//! Hard brakes: token / iteration / wall-clock enforcement.
//!
//! The most expensive unattended-loop failure is the *infinite-retry burn* — a
//! loop re-woken on an unrecoverable state, spending budget forever. The runtime
//! must not be able to exceed its caps even if the agent's logic says "try
//! again". This ledger makes the brakes structural: once a cap is reached,
//! `try_spend` / `tick` refuse, and the loop has no choice but to stop.

use serde::{Deserialize, Serialize};

/// Caps for a single loop run (a "trajectory"). `None` means uncapped on that axis.
#[derive(Debug, Clone, Copy, Serialize, Deserialize)]
pub struct Budget {
    pub max_tokens: Option<u64>,
    pub max_iterations: Option<u32>,
    pub wall_clock_secs: Option<u64>,
}

impl Budget {
    pub fn new(
        max_tokens: Option<u64>,
        max_iterations: Option<u32>,
        wall_clock_secs: Option<u64>,
    ) -> Self {
        Budget {
            max_tokens,
            max_iterations,
            wall_clock_secs,
        }
    }
}

/// Why a brake engaged.
#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum BrakeReason {
    TokenCeiling,
    IterationCap,
    WallClock,
}

/// Tracks spend against a `Budget`. `elapsed_secs` is injected rather than read
/// from a clock so the ledger is deterministic and unit-testable.
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct Ledger {
    budget: Budget,
    tokens_spent: u64,
    iterations: u32,
}

impl Ledger {
    pub fn new(budget: Budget) -> Self {
        Ledger {
            budget,
            tokens_spent: 0,
            iterations: 0,
        }
    }

    pub fn tokens_spent(&self) -> u64 {
        self.tokens_spent
    }

    pub fn iterations(&self) -> u32 {
        self.iterations
    }

    /// Attempt to spend tokens. Refuses (and records nothing) if it would breach
    /// the ceiling.
    pub fn try_spend(&mut self, tokens: u64) -> Result<(), BrakeReason> {
        if let Some(max) = self.budget.max_tokens {
            if self.tokens_spent + tokens > max {
                return Err(BrakeReason::TokenCeiling);
            }
        }
        self.tokens_spent += tokens;
        Ok(())
    }

    /// Advance one iteration. Refuses if it would exceed the iteration cap.
    pub fn tick(&mut self) -> Result<(), BrakeReason> {
        if let Some(max) = self.budget.max_iterations {
            if self.iterations + 1 > max {
                return Err(BrakeReason::IterationCap);
            }
        }
        self.iterations += 1;
        Ok(())
    }

    /// Check the wall-clock cap given elapsed seconds.
    pub fn check_wall_clock(&self, elapsed_secs: u64) -> Result<(), BrakeReason> {
        if let Some(limit) = self.budget.wall_clock_secs {
            if elapsed_secs > limit {
                return Err(BrakeReason::WallClock);
            }
        }
        Ok(())
    }

    /// True if any axis is exhausted (cannot do meaningful further work).
    pub fn exhausted(&self, elapsed_secs: u64) -> Option<BrakeReason> {
        if self.budget.max_iterations == Some(self.iterations) {
            return Some(BrakeReason::IterationCap);
        }
        if let Some(max) = self.budget.max_tokens {
            if self.tokens_spent >= max {
                return Some(BrakeReason::TokenCeiling);
            }
        }
        self.check_wall_clock(elapsed_secs).err()
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn token_ceiling_refuses_overspend() {
        let mut l = Ledger::new(Budget::new(Some(100), None, None));
        assert!(l.try_spend(60).is_ok());
        assert_eq!(l.try_spend(50), Err(BrakeReason::TokenCeiling));
        assert_eq!(l.tokens_spent(), 60); // refused spend not recorded
        assert!(l.try_spend(40).is_ok());
        assert_eq!(l.tokens_spent(), 100);
    }

    #[test]
    fn iteration_cap_kills_retry_burn() {
        let mut l = Ledger::new(Budget::new(None, Some(1), None));
        assert!(l.tick().is_ok());
        // single-pass loop: a second iteration is structurally impossible
        assert_eq!(l.tick(), Err(BrakeReason::IterationCap));
        assert_eq!(l.iterations(), 1);
    }

    #[test]
    fn wall_clock_trips_after_limit() {
        let l = Ledger::new(Budget::new(None, None, Some(300)));
        assert!(l.check_wall_clock(120).is_ok());
        assert_eq!(l.check_wall_clock(301), Err(BrakeReason::WallClock));
    }

    #[test]
    fn uncapped_axes_never_brake() {
        let mut l = Ledger::new(Budget::new(None, None, None));
        assert!(l.try_spend(10_000_000).is_ok());
        assert!(l.tick().is_ok());
        assert!(l.check_wall_clock(999_999).is_ok());
    }
}
