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

/// Does this git stderr indicate an *environment* failure (repo missing /
/// unreadable / not a repo) rather than a genuinely absent object? Such failures
/// must escalate as `Unverifiable`, never be mistaken for a fabricated SHA.
fn is_env_error(stderr: &str) -> bool {
    stderr.contains("Not a git repository")
        || stderr.contains("unable to read")
        || stderr.contains("cannot change to")
        || stderr.contains("No such file")
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
            if is_env_error(&stderr) {
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

// --- Isomorphic-perturbation verification ---------------------------------
//
// "LLMs Gaming Verifiers" (arXiv:2604.15149) and the Reward Hacking Benchmark
// (arXiv:2605.02964) converge on one finding: *extensional* verification — a
// single literal predicate the optimizer can target — induces reward hacking,
// while *isomorphic* verification prevents it. The defence is to check a claim
// under two independent-but-equivalent predicates and demand they agree. For an
// honest claim they always do; a *gap* (passes the literal check, fails the
// isomorphic variant) is the signature of a shortcut that satisfies the letter
// of the check without its intent.
//
// Here the literal predicate is "the short SHA resolves to a commit object"
// (`cat-file -e`). The isomorphic variant re-derives the *full* 40-hex oid
// (`rev-parse --verify`), confirms its object type is exactly `commit`, and
// confirms the claimed SHA is a genuine prefix of that oid. A truthful commit
// reference passes both; an ambiguous prefix, a tag/tree masquerading as a
// commit, or a fabricated-but-colliding id trips the gap.

/// The outcome of checking one claim under both predicates.
#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
#[serde(tag = "iso", rename_all = "snake_case")]
pub enum IsoVerdict {
    /// Both predicates agree the claim is grounded. Trustworthy.
    Consistent,
    /// Both predicates agree the claim is absent. An honest negative — the claim
    /// is simply false (fabricated), not a verifier shortcut.
    ConsistentAbsent,
    /// The predicates disagree: the literal check passes but the isomorphic
    /// variant fails (or vice-versa). This is the reward-hacking signature and
    /// must escalate — never treat a gap as grounded.
    Gap { detail: String },
    /// A predicate could not be evaluated (git missing / repo unreadable).
    Unverifiable { detail: String },
}

impl IsoVerdict {
    pub fn is_consistent_grounded(&self) -> bool {
        matches!(self, IsoVerdict::Consistent)
    }
}

/// Pure classifier: given whether the literal and isomorphic predicates each
/// found the claim grounded, decide the joint verdict. Agreement is trust;
/// disagreement is a shortcut. Kept separate from any git call so the decision
/// logic is exhaustively unit-tested without a repository.
pub fn classify_isomorphic(literal_ok: bool, variant_ok: bool) -> IsoVerdict {
    match (literal_ok, variant_ok) {
        (true, true) => IsoVerdict::Consistent,
        (false, false) => IsoVerdict::ConsistentAbsent,
        _ => IsoVerdict::Gap {
            detail: format!(
                "predicates disagree (literal={literal_ok}, isomorphic={variant_ok}): \
                 a claim that passes one ungameable check but not its equivalent is the \
                 signature of a verifier shortcut — escalating"
            ),
        },
    }
}

/// Is `claimed` a genuine prefix of the resolved full oid? Case-insensitive,
/// hex-only. Rejects an empty claim and any claim longer than the resolved id.
pub fn prefix_consistent(claimed: &str, resolved: &str) -> bool {
    if claimed.is_empty() || claimed.len() > resolved.len() {
        return false;
    }
    resolved.to_lowercase().starts_with(&claimed.to_lowercase())
}

/// Run the isomorphic variant: resolve the full oid, require object type
/// `commit`, and require the claimed SHA to be a prefix of the full oid.
fn variant_grounded(repo: &str, sha: &str) -> Result<bool, String> {
    let spec = format!("{sha}^{{commit}}");
    let full = Command::new("git")
        .args([
            "-C",
            repo,
            "rev-parse",
            "--verify",
            "--end-of-options",
            &spec,
        ])
        .output()
        .map_err(|e| format!("could not run git: {e}"))?;
    if !full.status.success() {
        let stderr = String::from_utf8_lossy(&full.stderr);
        if is_env_error(&stderr) {
            return Err(stderr.trim().to_string());
        }
        return Ok(false); // does not resolve under the variant either
    }
    let full_oid = String::from_utf8_lossy(&full.stdout).trim().to_string();

    let typ = Command::new("git")
        .args(["-C", repo, "cat-file", "-t", &full_oid])
        .output()
        .map_err(|e| format!("could not run git: {e}"))?;
    let object_type = String::from_utf8_lossy(&typ.stdout).trim().to_string();

    Ok(typ.status.success() && object_type == "commit" && prefix_consistent(sha, &full_oid))
}

/// Verify one claimed commit SHA under both the literal and isomorphic
/// predicates and return their joint verdict.
pub fn verify_commit_isomorphic(repo: &str, sha: &str) -> IsoVerdict {
    if sha.is_empty() || !sha.chars().all(|c| c.is_ascii_hexdigit()) {
        // Malformed input is consistently absent under both predicates.
        return IsoVerdict::ConsistentAbsent;
    }
    let literal_ok = verify_commit_sha(repo, sha).is_grounded();
    match variant_grounded(repo, sha) {
        Ok(variant_ok) => classify_isomorphic(literal_ok, variant_ok),
        Err(detail) => IsoVerdict::Unverifiable { detail },
    }
}

/// Verify a batch of SHAs isomorphically. The run is consistent only if no claim
/// shows a gap (a single gap invalidates the run, exactly like a fabricated SHA).
pub fn verify_batch_isomorphic(repo: &str, shas: &[String]) -> IsoBatchResult {
    let claims: Vec<IsoClaimVerdict> = shas
        .iter()
        .map(|sha| IsoClaimVerdict {
            sha: sha.clone(),
            verdict: verify_commit_isomorphic(repo, sha),
        })
        .collect();
    let gap = claims
        .iter()
        .any(|c| matches!(c.verdict, IsoVerdict::Gap { .. }));
    let unverifiable = claims
        .iter()
        .any(|c| matches!(c.verdict, IsoVerdict::Unverifiable { .. }));
    IsoBatchResult {
        consistent: !gap,
        gap,
        unverifiable,
        claims,
    }
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct IsoClaimVerdict {
    pub sha: String,
    pub verdict: IsoVerdict,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct IsoBatchResult {
    /// True iff no claim showed a literal/isomorphic gap.
    pub consistent: bool,
    /// At least one claim passed one predicate but not its equivalent.
    pub gap: bool,
    /// At least one claim could not be evaluated (escalate, don't trust).
    pub unverifiable: bool,
    pub claims: Vec<IsoClaimVerdict>,
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

    // --- isomorphic-perturbation ------------------------------------------

    #[test]
    fn agreement_is_consistent_either_way() {
        assert_eq!(classify_isomorphic(true, true), IsoVerdict::Consistent);
        assert_eq!(
            classify_isomorphic(false, false),
            IsoVerdict::ConsistentAbsent
        );
    }

    #[test]
    fn disagreement_is_a_gap_in_both_directions() {
        // Passes the literal check but not the isomorphic variant → shortcut.
        assert!(matches!(
            classify_isomorphic(true, false),
            IsoVerdict::Gap { .. }
        ));
        // The inverse asymmetry is just as suspicious.
        assert!(matches!(
            classify_isomorphic(false, true),
            IsoVerdict::Gap { .. }
        ));
    }

    #[test]
    fn prefix_consistency_is_case_insensitive_and_bounded() {
        assert!(prefix_consistent("abc", "ABCDEF0123"));
        assert!(prefix_consistent("ABC", "abcdef0123"));
        assert!(!prefix_consistent("abd", "abcdef0123")); // not a prefix
        assert!(!prefix_consistent("", "abcdef0123")); // empty claim
        assert!(!prefix_consistent("abcdef01234", "abcdef0123")); // longer than oid
    }

    #[test]
    fn malformed_sha_is_consistently_absent_not_a_gap() {
        // Garbage input must not look like a shortcut — both predicates reject it.
        assert_eq!(
            verify_commit_isomorphic("/nonexistent", "zzz!"),
            IsoVerdict::ConsistentAbsent
        );
    }

    #[test]
    fn iso_batch_unverifiable_when_repo_missing() {
        let r = verify_batch_isomorphic("/path/does/not/exist", &["deadbeef".to_string()]);
        // A repo we cannot read must escalate, never silently pass.
        assert!(r.unverifiable);
        assert!(!r.gap);
    }
}
