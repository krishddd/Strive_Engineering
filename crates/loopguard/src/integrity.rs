//! Diff-integrity scanner — defence against verifier tampering (reward hacking).
//!
//! The Reward Hacking Benchmark (arXiv:2605.02964) shows agents reliably discover
//! that the cheapest path to a green check is to *tamper with the check*: delete
//! the failing test, add a skip marker, weaken an assertion, or edit the eval
//! harness itself. "LLMs Gaming Verifiers" (arXiv:2604.15149) makes the same
//! point for RLVR. A loop that can edit code AND owns its verifier will find this
//! exploit by brute force unless something deterministic forbids it.
//!
//! This module scans a unified diff and flags those exact moves. It is
//! intentionally conservative: on an L2 change, any flagged move is an automatic
//! escalation to a human, not a soft warning.

use serde::{Deserialize, Serialize};

#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum IntegrityIssue {
    /// A test function/case was removed.
    TestRemoved,
    /// A skip/ignore/xfail marker was added.
    TestDisabled,
    /// An assertion was removed.
    AssertionRemoved,
    /// A file that *is* the verifier (tests/eval/ci) was modified.
    EvalFileTampered,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct IntegrityFinding {
    pub issue: IntegrityIssue,
    pub line: String,
    pub file: Option<String>,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct IntegrityReport {
    pub clean: bool,
    pub findings: Vec<IntegrityFinding>,
}

fn is_eval_path(path: &str) -> bool {
    let p = path.to_lowercase();
    p.contains("/test")
        || p.starts_with("test")
        || p.contains("_test.")
        || p.contains(".test.")
        || p.contains("/tests/")
        || p.contains("spec.")
        || p.contains("/eval")
        || p.contains("conftest")
        || p.contains(".github/workflows")
        || p.contains("/ci")
}

/// A removed line (`-` in a unified diff, ignoring `---` headers) that looks like
/// a test definition.
fn removed_is_test_def(body: &str) -> bool {
    let t = body.trim_start();
    t.starts_with("def test_")
        || t.starts_with("async def test_")
        || t.starts_with("#[test]")
        || t.starts_with("#[tokio::test]")
        || t.contains("it(")
        || t.contains("test(")
        || t.contains("describe(")
        || t.starts_with("func Test")
        || t.starts_with("@Test")
}

fn removed_is_assertion(body: &str) -> bool {
    let t = body.trim_start();
    t.starts_with("assert")
        || t.starts_with("expect(")
        || t.starts_with("self.assert")
        || t.contains("assert_eq!")
        || t.contains("assert_ne!")
        || t.contains("assert!(")
        || t.starts_with("require(")
}

/// An added line that disables a test.
fn added_disables_test(body: &str) -> bool {
    let t = body.trim_start();
    t.contains("@pytest.mark.skip")
        || t.contains("@unittest.skip")
        || t.contains("#[ignore]")
        || t.contains(".skip(")
        || t.contains("it.skip")
        || t.contains("describe.skip")
        || t.contains("xfail")
        || t.contains("@Disabled")
        || t.starts_with("t.Skip(")
}

/// Scan a unified diff for verifier-tampering moves.
pub fn scan_diff(diff: &str) -> IntegrityReport {
    let mut findings = Vec::new();
    let mut current_file: Option<String> = None;

    for line in diff.lines() {
        // Track the file under edit from `+++ b/path` headers.
        if let Some(rest) = line.strip_prefix("+++ ") {
            let path = rest.trim_start_matches("b/").trim();
            current_file = if path == "/dev/null" {
                None
            } else {
                Some(path.to_string())
            };
            continue;
        }
        if line.starts_with("--- ") || line.starts_with("diff ") || line.starts_with("@@") {
            continue;
        }

        let added = line.strip_prefix('+');
        let removed = line.strip_prefix('-');

        if let Some(body) = removed {
            if removed_is_test_def(body) {
                findings.push(IntegrityFinding {
                    issue: IntegrityIssue::TestRemoved,
                    line: body.trim().to_string(),
                    file: current_file.clone(),
                });
            } else if removed_is_assertion(body) {
                findings.push(IntegrityFinding {
                    issue: IntegrityIssue::AssertionRemoved,
                    line: body.trim().to_string(),
                    file: current_file.clone(),
                });
            }
        }
        if let Some(body) = added {
            if added_disables_test(body) {
                findings.push(IntegrityFinding {
                    issue: IntegrityIssue::TestDisabled,
                    line: body.trim().to_string(),
                    file: current_file.clone(),
                });
            }
            // Any addition to an eval/test/ci file is worth a human's eyes when
            // the same loop is trying to pass that very check.
            if let Some(f) = &current_file {
                if is_eval_path(f) && added_modifies_logic(body) {
                    findings.push(IntegrityFinding {
                        issue: IntegrityIssue::EvalFileTampered,
                        line: body.trim().to_string(),
                        file: current_file.clone(),
                    });
                }
            }
        }
    }

    IntegrityReport {
        clean: findings.is_empty(),
        findings,
    }
}

/// Heuristic: an added line in an eval file that changes logic (not a comment or
/// blank). Keeps the EvalFileTampered signal from firing on doc/comment churn.
fn added_modifies_logic(body: &str) -> bool {
    let t = body.trim();
    !t.is_empty() && !t.starts_with('#') && !t.starts_with("//") && !t.starts_with('*')
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn flags_removed_test_function() {
        let diff = "--- a/test_x.py\n+++ b/test_x.py\n@@\n-def test_login_fails():\n-    assert login() is False\n";
        let r = scan_diff(diff);
        assert!(!r.clean);
        assert!(r
            .findings
            .iter()
            .any(|f| f.issue == IntegrityIssue::TestRemoved));
    }

    #[test]
    fn flags_added_skip_marker() {
        let diff = "--- a/test_x.py\n+++ b/test_x.py\n@@\n+@pytest.mark.skip(reason=\"flaky\")\n def test_a():\n";
        let r = scan_diff(diff);
        assert!(r
            .findings
            .iter()
            .any(|f| f.issue == IntegrityIssue::TestDisabled));
    }

    #[test]
    fn flags_removed_assertion() {
        let diff = "--- a/m.py\n+++ b/m.py\n@@\n-    assert result == expected\n+    pass\n";
        let r = scan_diff(diff);
        assert!(r
            .findings
            .iter()
            .any(|f| f.issue == IntegrityIssue::AssertionRemoved));
    }

    #[test]
    fn flags_eval_file_logic_edit() {
        let diff = "--- a/tests/conftest.py\n+++ b/tests/conftest.py\n@@\n+    return True  # always pass\n";
        let r = scan_diff(diff);
        assert!(r
            .findings
            .iter()
            .any(|f| f.issue == IntegrityIssue::EvalFileTampered));
    }

    #[test]
    fn clean_diff_to_source_passes() {
        let diff = "--- a/src/lib.rs\n+++ b/src/lib.rs\n@@\n+pub fn add(a: i32, b: i32) -> i32 { a + b }\n";
        let r = scan_diff(diff);
        assert!(r.clean, "{:?}", r.findings);
    }

    #[test]
    fn comment_churn_in_eval_file_is_ignored() {
        let diff = "--- a/tests/x.py\n+++ b/tests/x.py\n@@\n+# clarify the fixture\n";
        let r = scan_diff(diff);
        assert!(r.clean);
    }
}
