//! L3 allowlist gate — decides whether a verified change may be auto-merged
//! without a human.
//!
//! L3 (unattended) is the most dangerous phase: the loop acts on its own. The
//! safety model says auto-action is permitted only for a tightly-scoped, boring,
//! low-blast-radius class of change. This module makes that decision
//! deterministically from a diff and a policy: a change auto-merges ONLY if every
//! touched file matches an allow glob, no file matches a deny glob, the change is
//! small (file/line caps), and the diff is integrity-clean (no verifier
//! tampering). Anything else escalates to a human — the L2 behavior.
//!
//! Globs are compiled to regex (reusing the `regex` dependency) rather than
//! pulling a glob crate, keeping the dependency graph pure-Rust.

use crate::integrity;
use regex::Regex;
use serde::{Deserialize, Serialize};

/// The auto-merge policy for an L3 loop.
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct AllowPolicy {
    /// Globs a changed file MUST match (at least one) to be eligible.
    pub allow_globs: Vec<String>,
    /// Globs that, if matched by ANY changed file, force escalation.
    #[serde(default)]
    pub deny_globs: Vec<String>,
    /// Max number of changed files for auto-merge.
    pub max_files: usize,
    /// Max number of added+removed lines for auto-merge.
    pub max_lines: usize,
}

impl AllowPolicy {
    /// A conservative default deny list for paths that must never auto-merge.
    pub fn default_deny() -> Vec<String> {
        [
            "**/auth/**",
            "**/payments/**",
            "**/billing/**",
            "**/secrets/**",
            "**/credentials/**",
            "**/migrations/**",
            ".github/workflows/**",
            "**/*.env",
            "**/Dockerfile*",
            "**/terraform/**",
            "**/k8s/**",
        ]
        .iter()
        .map(|s| s.to_string())
        .collect()
    }
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct PolicyDecision {
    /// True only if the change is safe to auto-merge unattended.
    pub auto_ok: bool,
    pub files_changed: usize,
    pub lines_changed: usize,
    /// Human-readable reasons for the decision (always populated on escalation).
    pub reasons: Vec<String>,
}

/// Convert a path glob to an anchored regex. Supports `**` (any path span,
/// including `/`), `*` (any run within a path segment), and `?`.
fn glob_to_regex(glob: &str) -> Regex {
    let mut re = String::from("(?s)^");
    let bytes = glob.as_bytes();
    let mut i = 0;
    while i < bytes.len() {
        match bytes[i] as char {
            '*' => {
                if i + 1 < bytes.len() && bytes[i + 1] as char == '*' {
                    re.push_str(".*"); // ** → any span incl. '/'
                    i += 2;
                    // swallow a following '/' so `**/x` also matches top-level `x`
                    if i < bytes.len() && bytes[i] as char == '/' {
                        re.push_str("/?");
                        i += 1;
                    }
                    continue;
                }
                re.push_str("[^/]*"); // * → within a segment
            }
            '?' => re.push_str("[^/]"),
            c if ".+()|[]{}^$\\".contains(c) => {
                re.push('\\');
                re.push(c);
            }
            c => re.push(c),
        }
        i += 1;
    }
    re.push('$');
    Regex::new(&re).expect("glob regex must compile")
}

/// Extract the set of changed file paths from a unified diff (from `+++ b/...`).
fn changed_files(diff: &str) -> Vec<String> {
    let mut files = Vec::new();
    for line in diff.lines() {
        if let Some(rest) = line.strip_prefix("+++ ") {
            let path = rest.trim_start_matches("b/").trim();
            if path != "/dev/null" && !files.iter().any(|f| f == path) {
                files.push(path.to_string());
            }
        }
    }
    files
}

/// Count added + removed content lines (excluding diff headers).
fn changed_lines(diff: &str) -> usize {
    diff.lines()
        .filter(|l| {
            (l.starts_with('+') && !l.starts_with("+++"))
                || (l.starts_with('-') && !l.starts_with("---"))
        })
        .count()
}

/// Evaluate a diff against a policy. Auto-merge only when every gate passes.
pub fn evaluate(diff: &str, policy: &AllowPolicy) -> PolicyDecision {
    let files = changed_files(diff);
    let lines = changed_lines(diff);
    let mut reasons = Vec::new();

    if files.is_empty() {
        reasons.push("no changed files detected in diff".into());
    }

    let allow_res: Vec<Regex> = policy
        .allow_globs
        .iter()
        .map(|g| glob_to_regex(g))
        .collect();
    let deny_res: Vec<Regex> = policy.deny_globs.iter().map(|g| glob_to_regex(g)).collect();

    for f in &files {
        if deny_res.iter().any(|r| r.is_match(f)) {
            reasons.push(format!("{f}: matches a deny glob"));
        }
        if !allow_res.iter().any(|r| r.is_match(f)) {
            reasons.push(format!("{f}: not covered by any allow glob"));
        }
    }
    if files.len() > policy.max_files {
        reasons.push(format!(
            "{} files > max_files {}",
            files.len(),
            policy.max_files
        ));
    }
    if lines > policy.max_lines {
        reasons.push(format!("{lines} lines > max_lines {}", policy.max_lines));
    }

    // Integrity is non-negotiable even inside the allowlist.
    let integrity = integrity::scan_diff(diff);
    if !integrity.clean {
        let issues: Vec<String> = integrity
            .findings
            .iter()
            .map(|f| format!("{:?}", f.issue))
            .collect();
        reasons.push(format!("verifier tampering: {issues:?}"));
    }

    PolicyDecision {
        auto_ok: reasons.is_empty(),
        files_changed: files.len(),
        lines_changed: lines,
        reasons,
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    fn policy() -> AllowPolicy {
        AllowPolicy {
            allow_globs: vec!["docs/**".into(), "**/*.md".into()],
            deny_globs: AllowPolicy::default_deny(),
            max_files: 3,
            max_lines: 50,
        }
    }

    #[test]
    fn auto_ok_for_small_allowlisted_change() {
        let diff = "--- a/docs/x.md\n+++ b/docs/x.md\n@@\n+a clarifying sentence\n";
        let d = evaluate(diff, &policy());
        assert!(d.auto_ok, "{:?}", d.reasons);
        assert_eq!(d.files_changed, 1);
    }

    #[test]
    fn escalates_outside_allowlist() {
        let diff = "--- a/src/core.rs\n+++ b/src/core.rs\n@@\n+fn x() {}\n";
        let d = evaluate(diff, &policy());
        assert!(!d.auto_ok);
        assert!(d.reasons.iter().any(|r| r.contains("not covered")));
    }

    #[test]
    fn escalates_on_deny_glob() {
        let diff = "--- a/app/auth/login.md\n+++ b/app/auth/login.md\n@@\n+x\n";
        let d = evaluate(diff, &policy());
        assert!(!d.auto_ok);
        assert!(d.reasons.iter().any(|r| r.contains("deny glob")));
    }

    #[test]
    fn escalates_when_too_large() {
        let mut diff = String::from("--- a/docs/x.md\n+++ b/docs/x.md\n@@\n");
        for i in 0..60 {
            diff.push_str(&format!("+line {i}\n"));
        }
        let d = evaluate(&diff, &policy());
        assert!(!d.auto_ok);
        assert!(d.reasons.iter().any(|r| r.contains("max_lines")));
    }

    #[test]
    fn escalates_on_integrity_violation_even_if_allowlisted() {
        let diff = "--- a/docs/test_x.md\n+++ b/docs/test_x.md\n@@\n-    assert x == 1\n";
        let d = evaluate(diff, &policy());
        assert!(!d.auto_ok);
        assert!(d.reasons.iter().any(|r| r.contains("tampering")));
    }

    #[test]
    fn double_star_matches_top_level() {
        let r = glob_to_regex("**/*.md");
        assert!(r.is_match("README.md"));
        assert!(r.is_match("docs/a/b.md"));
        assert!(!r.is_match("src/lib.rs"));
    }
}
