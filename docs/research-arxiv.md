# Research → features (annotated arXiv bibliography)

This file ties each capability in the runtime to the literature it implements.
The thesis throughout: *a loop is only as trustworthy as the verifier the
optimizer cannot game.* Every paper below either sharpens that verifier or
hardens the loop around it.

## 1. Reward hacking / verifier gaming → `loopguard::integrity`

- **Reward Hacking Benchmark: Measuring Exploits in LLM Agents with Tool Use** —
  arXiv:2605.02964. Catalogs concrete exploits agents discover: *skipping
  verification steps* and *tampering with evaluation functions*. Frontier exploit
  rates 0–13.9%.
- **LLMs Gaming Verifiers: RLVR can Lead to Reward Hacking** — arXiv:2604.15149.
  Introduces *Isomorphic Perturbation Testing*: check an output under both the
  literal verifier and an isomorphic variant; a gap reveals a shortcut.
- **Detecting and Mitigating Reward Hacking in RL: An Empirical Study** —
  arXiv:2507.05619.

→ **What we built:** `integrity` scans a proposed diff for the canonical
"verifier tampering" moves — deleted tests, added skip/ignore markers, removed or
weakened assertions, and edits to test/eval/verifier files themselves. The
runtime treats any such move on an L2 change as an automatic escalation. This is
the code-level analogue of "the cheapest way to a green check is to delete the
failing test."

## 2. Indirect prompt injection → `loopguard::injection`

- **The Task Shield: Enforcing Task Alignment to Defend Against Indirect Prompt
  Injection** — arXiv:2412.16682.
- **IPIGuard: Tool-Dependency-Graph Defense Against Indirect Prompt Injection** —
  arXiv:2508.15310 (EMNLP 2025).
- **Defense Against Indirect Prompt Injection via Tool Result Parsing** —
  arXiv:2601.04795.
- **VIGIL: Verify-Before-Commit against Tool Stream Injection** — arXiv:2601.05755.
- **PromptArmor / StruQ / PromptShield** — detection + structured-query defenses.

→ **What we built:** `injection` scans *untrusted tool-return text* (a fetched
page, a ticket body, a file the loop ingests) for injection signatures —
instruction-override ("ignore previous instructions"), role/system spoofing,
imperative tool directives, and exfiltration cues — and scores severity. Wired as
a **verify-before-commit** gate (VIGIL): a loop must scan ingested content before
acting on it.

## 3. LLM-as-judge is unreliable → self-consistency, never self-grade

- **Reliability without Validity: Large-Scale Evaluation of LLM-as-a-Judge** —
  arXiv:2606.19544. High test–retest reliability coexists with severe position
  bias (the "consistency–bias paradox").
- **Rating Roulette: Self-Inconsistency in LLM-as-a-Judge** — arXiv:2510.27106.
  Same input, same prompt → different verdicts across runs.
- **Do LLM Evaluators Prefer Themselves for a Reason?** — arXiv:2504.03846.
  Self-enhancement bias: models grade their own outputs higher.

→ **What we built:** (a) the runtime's checker is *never* the maker (separate
step), per self-enhancement bias; (b) `consistency` takes N independent verdicts
and requires a configurable majority, escalating on disagreement rather than
trusting any single judgment; (c) wherever a deterministic check exists (SHA
existence, diff integrity) we prefer it over an LLM judge entirely.

## 4. Iterate with reflection, not blind retry → `loopengine.reflexion`

- **Reflexion: Language Agents with Verbal Reinforcement Learning** — Shinn et
  al., NeurIPS 2023, arXiv:2303.11366. On failure, the agent writes a verbal
  self-critique into episodic memory and folds it into the next attempt.
- **Self-Refine: Iterative Refinement with Self-Feedback** — arXiv:2303.17651
  (the evaluator–optimizer pattern).

→ **What we built:** an `evaluator-optimizer` loop kind: maker proposes → checker
verifies (deterministic + consistency-voted) → on REJECT, a **reflection** is
written to episodic state and fed to the next attempt, bounded by the iteration
cap. This is the no-progress-oscillation fix with memory rather than a dumb retry.

## 5. One predicate is one shortcut → `loopguard::verifier` (isomorphic mode)

- **LLMs Gaming Verifiers: RLVR can Lead to Reward Hacking** — arXiv:2604.15149.
  The sharper claim beyond §1: *extensional* verification (a single literal
  predicate the optimizer can target) **induces** reward hacking, whereas
  *isomorphic* verification (the same claim checked under an equivalent variant)
  **prevents** it. Isomorphic Perturbation Testing is the black-box probe.
- **Benchmarking Reward Hack Detection in Code Environments via Contrastive
  Analysis** — arXiv:2601.20103. Detecting hacks by comparing behavior across
  semantically-equivalent environments — the same agree-or-flag idea applied to
  code.
- **Do Androids Dream of Breaking the Game? Auditing AI Agent Benchmarks with
  BenchJack** — arXiv:2605.12673. Benchmarks themselves are gameable; a check is
  only as trustworthy as its resistance to a shortcut.

→ **What we built:** `verify-iso` confirms every cited SHA under *two*
independent-but-equivalent predicates — the literal `cat-file -e`, and an
isomorphic variant that re-derives the full oid, requires object type `commit`,
and requires the claimed SHA to be a true prefix. Agreement is trust; a **gap**
(passes one ungameable check but not its equivalent) is the shortcut signature
and invalidates the run (exit 8), exactly like a fabricated SHA. The decision
logic is a pure, exhaustively-tested classifier separate from any git call.

## 6. Long loops overflow context → `loopengine.compaction`

- **Effective Context Engineering for AI Agents** — Anthropic (engineering blog,
  2025–2026). Names the levers that keep a long-horizon agent coherent:
  *compaction* (summarize older turns, preserve decisions/open bugs, drop
  redundant tool outputs), *structured note-taking* (a durable `NOTES.md` outside
  the window), *sub-agent context isolation*, and *just-in-time tool calling*.
- **Anthropic compaction API** (beta `compact-2026-01-12`) — summarize-and-drop
  above a configurable token threshold, with a `pause_after_compaction` hook to
  re-inject instructions before continuing. The production form of the same idea.
- Context-growth benchmarks corroborating the failure mode: **LOCA-bench**
  (arXiv:2602.07962), **SWE-EVO** (arXiv:2512.18470), **AgentSwing**
  (arXiv:2603.27490).

→ **What we built:** `Compactor` folds a transcript over a token threshold into a
decisions-and-open-items summary (dropping tool outputs, keeping the recent tail
verbatim) with an *injected* summarizer so it's deterministic and testable;
`Notebook` gives durable structured notes backed by the state spine, surviving
both compaction and process exit. The brake is structural — an unbounded
transcript is an unbounded cost — not advisory.

## 7. Loops get stuck or oscillate → `loopengine.scheduler` (anomaly guard)

- **AgentGuard** and the wider 2026 agent-observability tooling (loop detection,
  anomaly alerts, token/cost/latency/tool-failure gates) — the operational read
  of Reflexion's *no-progress* failure mode at the orchestration layer.

→ **What we built:** the scheduler keeps a bounded per-loop result history and a
pure `detect_anomaly` classifier that flags a **stall** (the same failing result
N times — stuck against one wall) or an **oscillation** (strict A/B flapping with
no progress). A flagged loop is **halted with an escalation note** instead of
re-run, the structural form of CLAUDE.md §8 — *it does not retry indefinitely and
does not guess.*

## Sources

- Reflexion — https://arxiv.org/abs/2303.11366
- Self-Refine — https://arxiv.org/abs/2303.17651
- Reward Hacking Benchmark — https://arxiv.org/abs/2605.02964
- LLMs Gaming Verifiers (RLVR) — https://arxiv.org/abs/2604.15149
- Detecting/Mitigating Reward Hacking — https://arxiv.org/abs/2507.05619
- Reliability without Validity (LLM-judge) — https://arxiv.org/abs/2606.19544
- Rating Roulette (judge self-inconsistency) — https://arxiv.org/abs/2510.27106
- Self-preference in LLM judges — https://arxiv.org/abs/2504.03846
- Task Shield — https://arxiv.org/abs/2412.16682
- IPIGuard — https://arxiv.org/abs/2508.15310
- Tool-Result-Parsing defense — https://arxiv.org/abs/2601.04795
- VIGIL (verify-before-commit) — https://arxiv.org/abs/2601.05755
- Contrastive reward-hack detection in code — https://arxiv.org/abs/2601.20103
- BenchJack (auditing agent benchmarks) — https://arxiv.org/abs/2605.12673
- Effective Context Engineering for AI Agents — https://www.anthropic.com/engineering/effective-context-engineering-for-ai-agents
- LOCA-bench (extreme context growth) — https://arxiv.org/abs/2602.07962
- SWE-EVO (long-horizon software evolution) — https://arxiv.org/abs/2512.18470
- AgentSwing (parallel context routing) — https://arxiv.org/abs/2603.27490
