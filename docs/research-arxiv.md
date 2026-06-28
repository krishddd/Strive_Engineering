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
