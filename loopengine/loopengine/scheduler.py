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
class TickItem:
    loop_id: str
    ran: bool
    result: str | None = None
    notify: bool = False
    reason: str = ""


@dataclass
class TickSummary:
    now: str
    items: list[TickItem] = field(default_factory=list)

    @property
    def notifications(self) -> list[TickItem]:
        return [i for i in self.items if i.notify]


class Scheduler:
    def __init__(self, state: StateStore, runner=None) -> None:
        self.state = state
        self.runner = runner or default_runner

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
            summary.items.append(
                TickItem(
                    loop_id,
                    ran=True,
                    result=result,
                    notify=result in NOTIFY_RESULTS,
                    reason="ran",
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
