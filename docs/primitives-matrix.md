# Primitives Matrix

Cross-tool mapping of the five building blocks. Fill in a column as we
actually start using a tool — don't pre-fill from assumption. Claude Code is
the primary build target; treat the rest as future-portability notes.

| Primitive | Claude Code | Codex | GitHub Actions (generic CI) |
|---|---|---|---|
| **Automations/Scheduling** | `/loop`, scheduled tasks, hooks at lifecycle events | Automations tab — project, prompt, cadence, local or background worktree | `schedule:` cron trigger in workflow YAML |
| **Worktrees** | `git worktree`, `--worktree` flag, `isolation: worktree` on subagents | Built-in worktree support for parallel threads | Separate job runners / checkout paths per job |
| **Skills** | `SKILL.md` in `.claude/skills/<name>/`, runs inline in current context | `$skill-name` invocation inside an automation prompt | Reusable composite actions / shared workflow templates (closest analog) |
| **Plugins/Connectors** | MCP servers | MCP servers | Marketplace actions, repository/org secrets-scoped API calls |
| **Sub-agents** | `.claude/agents/<name>.md`, own context window, returns summary | Spawned helper threads within an automation run | Separate jobs/workflows triggered by `workflow_dispatch` or `repository_dispatch` |
| **Memory/State** | `STATE.md`/`RUNLOG.md` (or any file/DB read+written each run) | Same pattern — external state file or external system | Workflow artifacts, repo files, or an external state store |
| **Context management** | Compaction (compaction API, beta `compact-2026-01-12`), memory tool, sub-agent isolation | Auto-compaction / summarization within a long thread | N/A per job (jobs are short-lived); push intermediate context to artifacts |

In this repo, context management is implemented tool-agnostically in
`loopengine.compaction` (threshold compaction + structured notes), so a long loop
stays bounded regardless of which agent tool runs the maker step.

## Notes

- Names overlap across tools but mechanics differ — don't assume a hook in
  Claude Code behaves like an equivalent-sounding feature elsewhere.
- When a pattern is ported to a second tool, add a row-level note here on
  what had to change, not just whether it worked.
