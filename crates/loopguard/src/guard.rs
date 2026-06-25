//! Deterministic command guard.
//!
//! The loop-engineering thesis: *the engineering resides entirely in the
//! constraints*. Advisory prose (a CLAUDE.md rule, a system prompt) holds only
//! probabilistically. This guard holds 100% of the time — a destructive command
//! is matched and refused before it can run, regardless of what the agent
//! "intended". It is the same job a Claude Code `PreToolUse` hook does, but as a
//! reusable, testable engine the runtime calls on every shell action.

use regex::Regex;
use serde::{Deserialize, Serialize};

/// The decision the guard returns for a candidate command.
#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
#[serde(tag = "decision", rename_all = "lowercase")]
pub enum Decision {
    /// Command is permitted.
    Allow,
    /// Command is refused; `rule` and `reason` explain why.
    Block { rule: String, reason: String },
}

impl Decision {
    pub fn is_block(&self) -> bool {
        matches!(self, Decision::Block { .. })
    }
}

struct Rule {
    name: &'static str,
    reason: &'static str,
    pattern: Regex,
}

/// A configurable denylist guard. Defaults encode the non-negotiable rules from
/// the safety model (no force-push, no history rewrite, no recursive force
/// delete, no writing secrets). Extra patterns can be layered on per project.
pub struct Guard {
    rules: Vec<Rule>,
}

impl Default for Guard {
    fn default() -> Self {
        Self::with_default_rules()
    }
}

impl Guard {
    pub fn with_default_rules() -> Self {
        let raw: &[(&'static str, &'static str, &str)] = &[
            (
                "git-force-push",
                "force-push / rewriting a shared branch is never automated",
                r"git\s+push\b[^\n]*(--force(\s|=|$)|--force-with-lease|\s-f(\s|$))",
            ),
            (
                "git-history-rewrite",
                "history rewrite / hard reset can destroy work",
                r"git\s+(rebase|filter-branch|filter-repo|reset\s+--hard)\b",
            ),
            (
                "git-destructive-ref",
                "destructive ref operation",
                r"git\s+(push[^\n]*--mirror|update-ref\s+-d)\b",
            ),
            (
                "rm-recursive-force",
                "recursive force delete",
                r"(^|\s)rm\s+-(?:[a-zA-Z]*[rR][a-zA-Z]*[fF]|[a-zA-Z]*[fF][a-zA-Z]*[rR])(\s|$)",
            ),
            (
                "powershell-recursive-force-delete",
                "recursive force delete (PowerShell)",
                r"Remove-Item\b[^\n]*(-Recurse[^\n]*-Force|-Force[^\n]*-Recurse)",
            ),
            (
                "write-env-file",
                "writing to a .env file",
                r">\s*[^>\n]*\.env(\.[A-Za-z0-9]+)?(\s|$)",
            ),
            (
                "write-secrets-path",
                "writing into a secrets / credentials path",
                r">\s*[^>\n]*(secrets?|credentials?)/",
            ),
            (
                "write-key-file",
                "writing to a key / pem file",
                r">\s*[^>\n]*\.(pem|key)(\s|$)",
            ),
        ];
        let rules = raw
            .iter()
            .map(|(name, reason, pat)| Rule {
                name,
                reason,
                pattern: Regex::new(pat).expect("built-in guard regex must compile"),
            })
            .collect();
        Guard { rules }
    }

    /// Add a custom denylist pattern (e.g. "no writes to the read-only triage
    /// target"). Returns Err if the pattern is not a valid regex.
    pub fn add_rule(
        &mut self,
        name: &'static str,
        reason: &'static str,
        pattern: &str,
    ) -> Result<(), regex::Error> {
        self.rules.push(Rule {
            name,
            reason,
            pattern: Regex::new(pattern)?,
        });
        Ok(())
    }

    /// Evaluate a command. First matching rule wins.
    pub fn check(&self, command: &str) -> Decision {
        for rule in &self.rules {
            if rule.pattern.is_match(command) {
                return Decision::Block {
                    rule: rule.name.to_string(),
                    reason: rule.reason.to_string(),
                };
            }
        }
        Decision::Allow
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    fn g() -> Guard {
        Guard::default()
    }

    #[test]
    fn blocks_force_push_variants() {
        assert!(g().check("git push --force origin main").is_block());
        assert!(g().check("git push -f origin main").is_block());
        assert!(g().check("git push --force-with-lease").is_block());
    }

    #[test]
    fn blocks_history_rewrite_and_hard_reset() {
        assert!(g().check("git rebase -i HEAD~3").is_block());
        assert!(g().check("git reset --hard origin/main").is_block());
        assert!(g()
            .check("git filter-branch --tree-filter x HEAD")
            .is_block());
    }

    #[test]
    fn blocks_recursive_force_delete() {
        assert!(g().check("rm -rf /tmp/x").is_block());
        assert!(g().check("rm -fr build/").is_block());
        assert!(g().check("sudo rm -Rf /").is_block());
    }

    #[test]
    fn blocks_writing_secrets() {
        assert!(g().check("echo TOKEN=abc > .env").is_block());
        assert!(g().check("cat x > config/secrets/prod.key").is_block());
    }

    #[test]
    fn allows_safe_readonly_commands() {
        assert_eq!(g().check("git log -5 --oneline"), Decision::Allow);
        assert_eq!(
            g().check("git cat-file -e deadbeef^{commit}"),
            Decision::Allow
        );
        assert_eq!(g().check("ls -la"), Decision::Allow);
        assert_eq!(g().check("git status"), Decision::Allow);
    }

    #[test]
    fn custom_rule_blocks_target_writes() {
        let mut guard = g();
        guard
            .add_rule(
                "readonly-target",
                "no writes to the read-only triage target",
                r"git\s+-C\s+\S*TARGET\S*\s+(commit|push|reset|checkout|merge)",
            )
            .unwrap();
        assert!(guard.check("git -C /repos/TARGET commit -m x").is_block());
        assert_eq!(guard.check("git -C /repos/TARGET log"), Decision::Allow);
    }
}
