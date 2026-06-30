"""Author, cost, and vet loop specs *before* they run.

Three small, dependency-free, deterministic helpers that make the runtime
useful to someone standing up a new loop — the equivalent of `loop-init`,
`loop-cost`, and `loop-audit` in the wider loop-engineering tooling, but wired
to *this* repo's schema and phase ladder:

* :func:`scaffold_spec` — emit a schema-valid starter spec for a chosen kind, so
  you fill in a target repo rather than memorize the schema.
* :func:`estimate_cost` — a rough per-run and per-day token estimate from the
  kind, the iteration cap, and the cadence, checked against the budget cap.
  Cost scales with fan-out and frequency far faster than intuition — see it
  before you deploy, not after the bill.
* :func:`audit_spec` — score a spec against the four things that make a loop a
  loop (trigger, verifier, external state, stop/escalate) plus the safety gates,
  and report the highest phase it is *structurally* ready for. The ladder is
  CLAUDE.md §5: start at L1, advance only when bored.

All three are pure functions over the spec dict, so they are trivially testable
and never touch the network, the model, or the target repo.
"""

from __future__ import annotations

from dataclasses import dataclass, field

# Rough per-run token cost by kind (order-of-magnitude, documented as heuristic).
# git-commit-triage is read-only with a modest window; assisted-fix carries a
# worktree snapshot through a maker+checker round and may retry up to the cap.
_KIND_BASE_TOKENS = {
    "git-commit-triage": 3_000,
    "assisted-fix": 30_000,
}
_SECONDS_PER_DAY = 86_400


# --- init / scaffolding ----------------------------------------------------

def scaffold_spec(loop_id: str, kind: str = "git-commit-triage") -> dict:
    """Return a schema-valid starter spec for ``kind``. The caller fills in the
    real ``target.repo`` (left as an obvious placeholder)."""
    if kind not in _KIND_BASE_TOKENS:
        raise ValueError(f"unknown loop kind {kind!r} (use one of {sorted(_KIND_BASE_TOKENS)})")
    if not loop_id:
        raise ValueError("loop_id is required")

    if kind == "git-commit-triage":
        return {
            "id": loop_id,
            "kind": kind,
            "phase": "L1",
            "cadence": "1d",
            "paused": False,
            "state_file": ".loop-state/state.json",
            "target": {
                "repo": "/absolute/path/to/your/target/repo",
                "refs": ["main"],
                "first_run_since": "7 days ago",
            },
            "budget": {"max_tokens": 50_000, "max_iterations": 1, "wall_clock_secs": 300},
        }
    # assisted-fix
    return {
        "id": loop_id,
        "kind": kind,
        "phase": "L2",
        "cadence": "1d",
        "paused": False,
        "state_file": ".loop-state/state.json",
        "target": {"repo": "/absolute/path/to/your/target/repo", "base_ref": "main"},
        "task": "Describe the narrow, allow-listed change to make, in plain language.",
        "test_command": "python -m pytest -q",
        "maker": {"type": "nvidia", "model": "meta/llama-3.3-70b-instruct"},
        "budget": {"max_tokens": 200_000, "max_iterations": 3, "wall_clock_secs": 600},
    }


# --- cost ------------------------------------------------------------------

@dataclass
class CostEstimate:
    per_run_tokens: int
    runs_per_day: float | None
    per_day_tokens: int | None
    budget_cap_tokens: int | None
    within_budget: bool | None
    notes: list[str] = field(default_factory=list)

    def as_dict(self) -> dict:
        return {
            "per_run_tokens": self.per_run_tokens,
            "runs_per_day": self.runs_per_day,
            "per_day_tokens": self.per_day_tokens,
            "budget_cap_tokens": self.budget_cap_tokens,
            "within_budget": self.within_budget,
            "notes": self.notes,
        }


def estimate_cost(spec: dict) -> CostEstimate:
    """Estimate per-run and per-day token spend for a spec. Heuristic, not a
    meter — its job is to catch an order-of-magnitude surprise before deploy."""
    from .scheduler import parse_interval

    kind = spec.get("kind", "")
    base = _KIND_BASE_TOKENS.get(kind, 5_000)
    notes: list[str] = []

    # assisted-fix may iterate up to the cap (Reflexion retries), each a full round.
    iterations = int((spec.get("budget") or {}).get("max_iterations", 1) or 1)
    per_run = base * iterations if kind == "assisted-fix" else base
    if kind == "assisted-fix" and iterations > 1:
        notes.append(f"assumes up to {iterations} maker/checker round(s) per run (iteration cap)")
    if kind not in _KIND_BASE_TOKENS:
        notes.append(f"unknown kind {kind!r} — using a generic {base:,}-token estimate")

    runs_per_day: float | None = None
    cadence = spec.get("cadence")
    if cadence:
        try:
            secs = parse_interval(cadence)
            runs_per_day = round(_SECONDS_PER_DAY / secs, 2) if secs else None
        except ValueError:
            notes.append(f"unparseable cadence {cadence!r} — per-day estimate omitted")
    else:
        notes.append("no cadence — on-demand only; per-day estimate omitted")

    per_day = int(per_run * runs_per_day) if runs_per_day else None

    cap = (spec.get("budget") or {}).get("max_tokens")
    within = None
    if cap is not None:
        within = per_run <= cap
        if not within:
            notes.append(f"per-run estimate {per_run:,} exceeds the budget cap {cap:,} — raise the cap or narrow the loop")

    return CostEstimate(per_run, runs_per_day, per_day, cap, within, notes)


# --- audit -----------------------------------------------------------------

@dataclass
class Check:
    name: str
    ok: bool
    detail: str


@dataclass
class AuditReport:
    loop_id: str
    kind: str
    ready_for: str  # "L0".."L3" — highest phase the spec is structurally ready for
    declared_phase: str
    score: int  # 0..100 over all checks
    checks: list[Check]
    suggestions: list[str] = field(default_factory=list)

    def as_dict(self) -> dict:
        return {
            "loop_id": self.loop_id,
            "kind": self.kind,
            "declared_phase": self.declared_phase,
            "ready_for": self.ready_for,
            "score": self.score,
            "checks": [{"name": c.name, "ok": c.ok, "detail": c.detail} for c in self.checks],
            "suggestions": self.suggestions,
        }


def audit_spec(spec: dict) -> AuditReport:
    """Score a spec against the loop pillars + safety gates and report the
    highest phase it is structurally ready for (independent of the phase it
    *declares* — a mismatch is exactly what this surfaces)."""
    kind = spec.get("kind", "")
    budget = spec.get("budget") or {}
    target = spec.get("target") or {}
    checks: list[Check] = []
    suggestions: list[str] = []

    def add(name: str, ok: bool, detail: str, suggestion: str | None = None) -> bool:
        checks.append(Check(name, ok, detail))
        if not ok and suggestion:
            suggestions.append(suggestion)
        return ok

    # Pillar 1 — trigger (a scored check + autonomy hint; does not gate the phase)
    add(
        "trigger",
        bool(spec.get("cadence")),
        f"cadence={spec.get('cadence')!r}" if spec.get("cadence") else "no cadence (manual/on-demand only)",
        "add a 'cadence' (e.g. '1d') so the scheduler can run it autonomously",
    )

    # Pillar 2 — verifier (kind-appropriate)
    if kind == "git-commit-triage":
        has_verifier = add("verifier", True, "grounded SHA verification (built-in, ungameable)")
    elif kind == "assisted-fix":
        tc = bool(spec.get("test_command"))
        has_verifier = add(
            "verifier",
            tc,
            f"test_command={spec.get('test_command')!r}" if tc else "no test_command (no ground-truth check)",
            "add a 'test_command' — the ground-truth verifier the loop iterates against",
        )
    else:
        has_verifier = add("verifier", False, f"unknown kind {kind!r}", "set 'kind' to a supported loop type")

    # Pillar 3 — external state
    add("external_state", True, f"state_file={spec.get('state_file', '.loop-state/state.json')!r} (defaulted if absent)")

    # Pillar 4 — stop / escalate (a brake must exist)
    has_brake = bool(budget.get("max_iterations") or budget.get("max_tokens") or budget.get("wall_clock_secs"))
    add(
        "stop_escalate",
        has_brake,
        "budget brake present" if has_brake else "no budget cap — could run unbounded",
        "set at least one budget cap (max_tokens / max_iterations / wall_clock_secs)",
    )

    # Budget cap explicitly (token ceiling)
    add(
        "budget_cap",
        budget.get("max_tokens") is not None,
        f"max_tokens={budget.get('max_tokens')}" if budget.get("max_tokens") is not None else "no max_tokens",
        "set budget.max_tokens to bound spend per run",
    )

    # L2 readiness — an agent maker to propose changes
    has_maker = kind == "assisted-fix" and bool(spec.get("maker") or spec.get("maker_command"))
    if kind == "assisted-fix":
        add(
            "maker",
            has_maker,
            "maker configured" if has_maker else "no maker / maker_command",
            "add a 'maker' (llm/nvidia/openai) or 'maker_command' so the loop can propose edits",
        )

    # L3 readiness — an allowlist gate for auto-merge
    has_allowlist = bool(spec.get("allowlist"))
    if spec.get("phase") == "L3" or has_allowlist:
        add(
            "l3_allowlist",
            has_allowlist,
            "allowlist gate present" if has_allowlist else "L3 declared without an allowlist gate",
            "define an 'allowlist' (allow_globs/deny_globs/max_files/max_lines) before running unattended",
        )

    # --- derive the highest structurally-ready phase ----------------------
    # The L-ladder is about *blast radius of action*, not scheduling: a loop can
    # be L2 (proposes changes) whether it's triggered on a cadence or run by hand
    # (`loopengine run`). So the trigger is a scored check and an autonomy
    # suggestion, but it does not gate the phase level — only the action-capable
    # primitives (verifier, brake, maker, allowlist) do.
    base_ok = has_verifier and has_brake  # the minimum to be a real loop at all
    ready = "L0"
    if base_ok:
        ready = "L1"
    if ready == "L1" and kind == "assisted-fix" and has_maker:
        ready = "L2"
    if ready == "L2" and has_allowlist:
        ready = "L3"

    if spec.get("phase") and _phase_rank(spec["phase"]) > _phase_rank(ready):
        suggestions.insert(
            0,
            f"declares {spec['phase']} but is only structurally ready for {ready} — "
            f"close the gap before advancing (CLAUDE.md §5)",
        )

    passed = sum(1 for c in checks if c.ok)
    score = round(100 * passed / len(checks)) if checks else 0

    return AuditReport(
        loop_id=spec.get("id", "<no id>"),
        kind=kind,
        ready_for=ready,
        declared_phase=spec.get("phase", "<none>"),
        score=score,
        checks=checks,
        suggestions=suggestions,
    )


def _phase_rank(phase: str) -> int:
    return {"L0": 0, "L1": 1, "L2": 2, "L3": 3}.get(phase, -1)
