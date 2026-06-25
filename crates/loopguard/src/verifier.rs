//! Grounded verification primitives.
//!
//! "The verifier is the whole game." A loop iterates until a check passes, so any
//! gap between *passing the check* and *being correct* gets brute-forced into an
//! exploit. The defence is a verifier the optimizer cannot game: deterministic,
//! external, and checkable. The canonical example here — does a claimed commit
//! SHA actually exist in the target repo? — is ungameable: a SHA either resolves
//! or it doesn't. A loop cannot talk its way past `git cat-file`.

use serde::{Deserialize, Serialize};
use std::process::Command;

/// The outcome of verifying a single grounded claim.
#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
#[serde(tag = "verdict", rename_all = "snake_case")]
pub enum Verdict {
    /// The claim is grounded (the artifact exists).
    Grounded,
    /// The claim is fabricated (the artifact does not exist). A run containing
    /// any fabricated claim is invalid.
    Fabricated { detail: String },
    /// The verifier itself could not run (e.g. git missing, repo unreadable).
    /// This must escalate — it must never be silently treated as "grounded".
    Unverifiable { detail: String },
}

impl Verdict {
    pub fn is_grounded(&self) -> bool {
        matches!(self, Verdict::Grounded)
    }
}

/// Verify that `sha` resolves to a commit object in the git repo at `repo`.
/// Read-only: runs only `git -C <repo> cat-file -e <sha>^{commit}`.
pub fn verify_commit_sha(repo: &str, sha: &str) -> Verdict {
    // Reject obviously malformed input before shelling out.
    if sha.is_empty() || !sha.chars().all(|c| c.is_ascii_hexdigit()) {
        return Verdict::Fabricated {
            detail: format!("'{sha}' is not a hexadecimal object id"),
        };
    }

    let spec = format!("{sha}^{{commit}}");
    let output = Command::new("git")
        .args(["-C", repo, "cat-file", "-e", &spec])
        .output();

    match output {
        Ok(o) if o.status.success() => Verdict::Grounded,
        Ok(o) => {
            let stderr = String::from_utf8_lossy(&o.stderr);
            // git distinguishes "bad object" (fabricated) from environment errors.
            if stderr.contains("Not a git repository") || stderr.contains("unable to read") {
                Verdict::Unverifiable {
                    detail: stderr.trim().to_string(),
                }
            } else {
                Verdict::Fabricated {
                    detail: format!("{sha} does not resolve to a commit"),
                }
            }
        }
        Err(e) => Verdict::Unverifiable {
            detail: format!("could not run git: {e}"),
        },
    }
}

/// Verify a batch of SHAs. The run is valid only if *every* claim is grounded.
/// Returns the per-claim verdicts plus an overall `valid` flag.
pub fn verify_batch(repo: &str, shas: &[String]) -> BatchResult {
    let claims: Vec<ClaimVerdict> = shas
        .iter()
        .map(|sha| ClaimVerdict {
            sha: sha.clone(),
            verdict: verify_commit_sha(repo, sha),
        })
        .collect();
    let valid = claims.iter().all(|c| c.verdict.is_grounded());
    BatchResult { valid, claims }
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct ClaimVerdict {
    pub sha: String,
    pub verdict: Verdict,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct BatchResult {
    pub valid: bool,
    pub claims: Vec<ClaimVerdict>,
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn malformed_sha_is_fabricated_without_running_git() {
        assert!(matches!(
            verify_commit_sha("/nonexistent", "not-hex!"),
            Verdict::Fabricated { .. }
        ));
    }

    #[test]
    fn missing_repo_is_unverifiable_not_grounded() {
        let v = verify_commit_sha("/path/that/does/not/exist", "deadbeef");
        // Must never be Grounded for a repo we can't read.
        assert!(!v.is_grounded());
    }

    #[test]
    fn batch_invalid_if_any_claim_ungrounded() {
        let r = verify_batch("/nonexistent", &["abc123".to_string()]);
        assert!(!r.valid);
        assert_eq!(r.claims.len(), 1);
    }
}
