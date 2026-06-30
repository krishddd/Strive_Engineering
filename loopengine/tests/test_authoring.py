"""Tests for the spec-authoring helpers: init/scaffold, cost, audit. Pure and
deterministic — no network, no target repo, no model."""

from __future__ import annotations

import pytest

from loopengine.authoring import audit_spec, estimate_cost, scaffold_spec
from loopengine.validate import SpecInvalid, validate_spec


# -- scaffold ---------------------------------------------------------------

@pytest.mark.parametrize("kind", ["git-commit-triage", "assisted-fix"])
def test_scaffold_is_schema_valid(kind):
    spec = scaffold_spec("my-loop", kind)
    assert spec["id"] == "my-loop" and spec["kind"] == kind
    validate_spec(spec)  # raises SpecInvalid if the scaffold violates the schema


def test_scaffold_rejects_unknown_kind_and_empty_id():
    with pytest.raises(ValueError):
        scaffold_spec("x", "not-a-kind")
    with pytest.raises(ValueError):
        scaffold_spec("", "git-commit-triage")


# -- cost -------------------------------------------------------------------

def test_cost_scales_with_iterations_and_cadence():
    spec = scaffold_spec("a", "assisted-fix")
    spec["budget"]["max_iterations"] = 3
    spec["cadence"] = "1d"
    est = estimate_cost(spec)
    # assisted-fix base (30k) * 3 attempts
    assert est.per_run_tokens == 90_000
    assert est.runs_per_day == 1.0
    assert est.per_day_tokens == 90_000


def test_cost_flags_when_per_run_exceeds_cap():
    spec = scaffold_spec("a", "assisted-fix")
    spec["budget"]["max_iterations"] = 5
    spec["budget"]["max_tokens"] = 10_000  # far below the estimate
    est = estimate_cost(spec)
    assert est.within_budget is False
    assert any("exceeds the budget cap" in n for n in est.notes)


def test_cost_handles_missing_cadence():
    spec = scaffold_spec("a", "git-commit-triage")
    del spec["cadence"]
    est = estimate_cost(spec)
    assert est.runs_per_day is None and est.per_day_tokens is None
    assert any("on-demand" in n for n in est.notes)


# -- audit ------------------------------------------------------------------

def test_audit_healthy_triage_is_ready_for_l1():
    report = audit_spec(scaffold_spec("t", "git-commit-triage"))
    assert report.ready_for == "L1"
    assert report.score == 100
    assert {c.name for c in report.checks} >= {"trigger", "verifier", "external_state", "stop_escalate"}


def test_audit_flags_phase_overreach():
    spec = scaffold_spec("t", "git-commit-triage")
    spec["phase"] = "L3"  # declares far above what a read-only triage can support
    report = audit_spec(spec)
    assert report.ready_for == "L1"
    assert any("declares L3" in s for s in report.suggestions)


def test_audit_assisted_fix_needs_maker_for_l2():
    spec = scaffold_spec("f", "assisted-fix")
    spec.pop("maker", None)
    report = audit_spec(spec)
    assert report.ready_for == "L1"  # no maker → not L2-ready
    assert any("maker" in s for s in report.suggestions)


def test_audit_missing_brake_is_not_a_loop():
    spec = scaffold_spec("t", "git-commit-triage")
    spec["budget"] = {}  # no caps at all
    report = audit_spec(spec)
    assert report.ready_for == "L0"
    assert any(c.name == "stop_escalate" and not c.ok for c in report.checks)
