"""Multi-loop scheduler — run several loops on a cadence, in priority order.

This is the *automation* primitive at the top of the stack: it decides which
loops are due, runs them in priority order, and applies the operating-loops
discipline from the docs:

* **Cadence** — a loop runs only if its interval has elapsed since its last run
  (read from STATE). The clock is injected (``now``), so this is deterministic and
  testable without sleeping.
* **Triage-inbox / no notification fatigue** — a run that found nothing (``clean``)
  is recorded but flagged ``notify=False``; only actionable results (found /
  proposed / merged / escalated / error) surface to a human.
* **Collision guard** — two loops that *write* to the same target are not both run
  in one tick; the second is skipped with a note (multi-loop coordination).
* **Kill switch** — a paused loop is skipped.
* **Anomaly guard** — a loop that is *stuck* (the same failing result over and
  over) or *oscillating* (flapping between two states with no progress) is
  detected and halted with an escalation note, rather than re-run indefinitely.
  This is the structural form of CLAUDE.md §8 — "it does not retry indefinitely
  and does not guess" — and the operational read of Reflexion's no-progress
  failure mode (fix A breaks B, fix B breaks A).

The per-loop runner is injected, so the scheduler is tested without real loops;
``default_runner`` dispatches a spec to the right loop runtime by ``kind``.
"""

from __future__ import annotations

import datetime as _dt
import re
from dataclasses import dataclass, field

from .state import StateStore

# Results that are "news" — everything else is a quiet/clean run.
NOTIFY_RESULTS = {"found", "proposed", "merged", "escalated", "error"}
# Loops whose kind can write to their target (collision-relevant).
WRITING_KINDS = {"assisted-fix"}
# Results that signal "stuck against the same wall" (never includes clean/found —
# a loop that's quietly clean every run is *healthy*, not anomalous).
STUCK_RESULTS = {"error", "escalated"}
# How many recent results to retain per loop for anomaly detection.
ANOMALY_HISTORY = 8

_INTERVAL_RE = re.compile(r"^\s*(\d+)\s*([smhd])\s*$")


def parse_interval(text: str) -> int:
    """Parse '30s' / '5m' / '2h' / '1d' into seconds."""
    m = _INTERVAL_RE.match(text)
    if not m:
        raise ValueError(f"bad interval: {text!r} (use e.g. 30s, 5m, 2h, 1d)")
    n, unit = int(m.group(1)), m.group(2)
    return n * {"s": 1, "m": 60, "h": 3600, "d": 86400}[unit]


def _parse_ts(ts: str | None) -> _dt.datetime | None:
    if not ts:
        return None
    try:
        return _dt.datetime.strptime(ts, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=_dt.timezone.utc)
    except ValueError:
        return None


@dataclass
class AnomalyVerdict:
    """Whether a loop's recent result history shows a pathological pattern.

    ``kind`` is ``None`` (healthy), ``"stall"`` (stuck against the same wall), or
    ``"oscillation"`` (flapping between two states with no net progress).
    """

    kind: str | None
    detail: str = ""

    @property
    def halting(self) -> bool:
        # A stall is hard-stuck: stop re-running it. Oscillation is surfaced and
        # halted too — repeating it just burns tokens for no progress.
        return self.kind in {"stall", "oscillation"}


def detect_anomaly(results: list[str], *, stall_n: int = 3, oscillation_n: int = 4) -> AnomalyVerdict:
    """Classify a result history (most-recent-last) as healthy / stall / oscillation.

    Pure and deterministic — the scheduler persists the history and feeds it here.
    """
    n = len(results)
    if n >= stall_n:
        tail = results[-stall_n:]
        if len(set(tail)) == 1 and tail[0] in STUCK_RESULTS:
            return AnomalyVerdict(
                "stall",
                f"{stall_n} consecutive {tail[0]!r} results — stuck; escalating instead of retrying",
            )
    if n >= oscillation_n:
        tail = results[-oscillation_n:]
        if len(set(tail)) == 2:
            a, b = tail[0], tail[1]
            if a != b and all(tail[i] == (a if i % 2 == 0 else b) for i in range(oscillation_n)):
                return AnomalyVerdict(
                    "oscillation",
                    f"results alternate {a!r}/{b!r} with no progress — escalating",
                )
    return AnomalyVerdict(None)


@dataclass
class TickItem:
    loop_id: str
    ran: bool
    result: str | None = None
    notify: bool = False
    reason: str = ""
    anomaly: str | None = None


@dataclass
class TickSummary:
    now: str
    items: list[TickItem] = field(default_factory=list)

    @property
    def notifications(self) -> list[TickItem]:
        return [i for i in self.items if i.notify]


class Scheduler:
    def __init__(self, state: StateStore, runner=None, halt_on_anomaly: bool = True) -> None:
        self.state = state
        self.runner = runner or default_runner
        self.halt_on_anomaly = halt_on_anomaly

    # Scheduler bookkeeping lives in a sibling section so it never collides with
    # the section the loop's own runtime overwrites each run.
    @staticmethod
    def _sched_id(loop_id: str) -> str:
        return f"{loop_id}::sched"

    def _sched_section(self, loop_id: str) -> dict:
        return self.state.read_section(self._sched_id(loop_id))

    def _record_result(self, loop_id: str, result: str) -> AnomalyVerdict:
        """Append a result to the loop's bounded history and classify it."""
        section = self._sched_section(loop_id)
        history = list(section.get("history", []))
        history.append(result)
        history = history[-ANOMALY_HISTORY:]
        verdict = detect_anomaly(history)
        section["history"] = history
        if verdict.kind:
            section["anomaly"] = verdict.kind
            section["anomaly_detail"] = verdict.detail
        else:
            section.pop("anomaly", None)
            section.pop("anomaly_detail", None)
        self.state.write_section(self._sched_id(loop_id), section)
        return verdict

    def _due(self, spec: dict, now: _dt.datetime) -> bool:
        cadence = spec.get("cadence")
        if not cadence:
            return True  # no cadence → always eligible
        last = _parse_ts(self.state.read_section(spec["id"]).get("last_run"))
        if last is None:
            return True
        return (now - last).total_seconds() >= parse_interval(cadence)

    def run_once(self, specs: list[dict], now: str) -> TickSummary:
        """Run every due loop once, highest priority first. ``now`` is an ISO8601
        UTC string (injected — no wall-clock dependency)."""
        now_dt = _parse_ts(now) or _dt.datetime.now(_dt.timezone.utc)
        summary = TickSummary(now=now)
        claimed_targets: set[str] = set()

        for spec in sorted(specs, key=lambda s: s.get("priority", 100)):
            loop_id = spec["id"]
            if spec.get("paused"):
                summary.items.append(TickItem(loop_id, ran=False, reason="paused"))
                continue
            # Anomaly halt: a loop flagged stuck/oscillating on a prior tick is not
            # re-run — it has escalated to a human (CLAUDE.md §8: no retry loops).
            prior = self._sched_section(loop_id)
            if self.halt_on_anomaly and prior.get("anomaly") in {"stall", "oscillation"}:
                summary.items.append(
                    TickItem(
                        loop_id,
                        ran=False,
                        notify=True,
                        anomaly=prior["anomaly"],
                        reason=f"halted ({prior['anomaly']}) — awaiting human: {prior.get('anomaly_detail', '')}",
                    )
                )
                continue
            if not self._due(spec, now_dt):
                summary.items.append(TickItem(loop_id, ran=False, reason="not due"))
                continue

            # Collision guard: don't run two writers against the same target in one tick.
            target = (spec.get("target") or {}).get("repo")
            if spec.get("kind") in WRITING_KINDS and target:
                if target in claimed_targets:
                    summary.items.append(
                        TickItem(loop_id, ran=False, reason=f"target {target} already claimed this tick")
                    )
                    continue
                claimed_targets.add(target)

            result = self.runner(spec, self.state)
            verdict = self._record_result(loop_id, result)
            summary.items.append(
                TickItem(
                    loop_id,
                    ran=True,
                    result=result,
                    notify=result in NOTIFY_RESULTS or verdict.halting,
                    anomaly=verdict.kind,
                    reason=verdict.detail or "ran",
                )
            )
        return summary


def default_runner(spec: dict, state: StateStore) -> str:
    """Dispatch a spec to the right loop runtime by kind; return its result string."""
    kind = spec.get("kind")
    if kind == "git-commit-triage":
        from .runtime import LoopRuntime

        return LoopRuntime(spec, state).run().result
    if kind == "assisted-fix":
        from .assisted import AssistedFixLoop
        from .makers import make_maker

        maker = make_maker(spec["maker"]) if spec.get("maker") else None
        return AssistedFixLoop(spec, state, maker=maker).run().result
    raise ValueError(f"scheduler cannot run loop kind {kind!r}")
