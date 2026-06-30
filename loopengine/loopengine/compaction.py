"""Context compaction + structured note-taking — keep long loops from overflowing.

A loop that runs many iterations accumulates transcript faster than intuition
suggests, and a coding agent's context window is finite. Anthropic's *Effective
Context Engineering for AI Agents* names the levers that keep a long-horizon
agent coherent instead of drowning in its own history:

* **Compaction** — when the transcript nears a token threshold, summarize the
  older turns (preserving architectural decisions and unresolved bugs) and
  *drop the redundant tool outputs*, then continue from a compact summary plus
  the most recent turns. This is the single highest-leverage move: tool returns
  are the bulk of the tokens and almost never need to be re-read verbatim.
* **Structured note-taking** — a durable scratch memory *outside* the context
  window (the moral equivalent of a ``NOTES.md`` the agent maintains), written
  during a run and selectively reloaded later. Survives compaction by living in
  the state spine, not the transcript.

Both are deterministic here: the summarizer is an injected callable, so the
controller is testable without a network or a model. In production you can pass
an LLM summarizer; the default :func:`extractive_summary` is a dependency-free
heuristic that keeps decision/blocker lines and discards tool noise.

The thesis of the repo holds: this is a *constraint*, not a nicety — an
unbounded transcript is an unbounded cost and an eventual hard failure, so the
brake is structural (a threshold the loop cannot exceed), not advisory.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable, Sequence

# Lines whose content tends to carry forward-looking value worth preserving
# across a compaction — decisions made, problems still open, constraints to obey.
_KEEP_MARKERS = (
    "decision",
    "decided",
    "chose",
    "because",
    "constraint",
    "must",
    "todo",
    "open",
    "unresolved",
    "bug",
    "error",
    "fail",
    "blocked",
    "next",
    "escalat",
    "regress",
)


def estimate_tokens(text: str) -> int:
    """Cheap, deterministic token estimate (~4 chars/token). Good enough to drive
    a threshold without a tokenizer dependency; the brake only needs to be
    monotonic, not exact."""
    return (len(text) + 3) // 4


@dataclass
class Message:
    """One transcript turn. ``pinned`` turns (the task brief, the system prompt,
    a compaction summary) are never dropped or summarized away."""

    role: str  # "system" | "user" | "assistant" | "tool"
    content: str
    pinned: bool = False

    @property
    def tokens(self) -> int:
        return estimate_tokens(self.content)


# A summarizer turns a run of older messages into a compact text summary.
Summarizer = Callable[[Sequence[Message]], str]


@dataclass
class CompactionResult:
    messages: list[Message]
    compacted: bool
    summary: str | None
    tokens_before: int
    tokens_after: int
    dropped: int = field(default=0)  # how many older messages were folded away


def extractive_summary(messages: Sequence[Message]) -> str:
    """Dependency-free default summarizer: keep salient lines (decisions, open
    bugs, blockers, next-steps), drop tool outputs wholesale. Order-preserving
    and de-duplicated. This mirrors compaction's intent — *maximize recall of
    what still matters, eliminate what won't be re-read.*"""
    out: list[str] = []
    seen: set[str] = set()
    for m in messages:
        if m.role == "tool":
            continue  # the canonical drop: redundant tool returns
        for raw in m.content.splitlines():
            line = raw.strip()
            if not line:
                continue
            low = line.lower()
            if any(marker in low for marker in _KEEP_MARKERS):
                bullet = f"- {line}"
                if bullet not in seen:
                    seen.add(bullet)
                    out.append(bullet)
    if not out:
        return "(no salient decisions or open items found in the compacted range)"
    return "\n".join(out[:60])


class Compactor:
    """Threshold-driven transcript compactor.

    When the running transcript exceeds ``threshold_tokens``, fold every
    non-pinned message older than the most recent ``keep_recent`` into a single
    summary message (itself pinned, so a later compaction never re-summarizes
    it), preserving pinned messages and the recent tail verbatim.
    """

    def __init__(
        self,
        threshold_tokens: int = 12000,
        keep_recent: int = 6,
        summarizer: Summarizer | None = None,
    ) -> None:
        if threshold_tokens < 1:
            raise ValueError("threshold_tokens must be >= 1")
        if keep_recent < 0:
            raise ValueError("keep_recent must be >= 0")
        self.threshold_tokens = threshold_tokens
        self.keep_recent = keep_recent
        self.summarizer = summarizer or extractive_summary

    def total_tokens(self, messages: Sequence[Message]) -> int:
        return sum(m.tokens for m in messages)

    def maybe_compact(self, messages: Sequence[Message]) -> CompactionResult:
        """Compact iff the transcript is over threshold; otherwise a no-op."""
        msgs = list(messages)
        before = self.total_tokens(msgs)
        if before <= self.threshold_tokens:
            return CompactionResult(msgs, False, None, before, before, 0)

        pinned = [m for m in msgs if m.pinned]
        rest = [m for m in msgs if not m.pinned]
        recent = rest[len(rest) - self.keep_recent :] if self.keep_recent else []
        older = rest[: len(rest) - len(recent)]

        new_messages = list(pinned)
        summary_text: str | None = None
        if older:
            summary_text = self.summarizer(older)
            new_messages.append(
                Message(
                    role="system",
                    content=(
                        f"[compacted: {len(older)} earlier message(s) summarized; "
                        f"tool outputs dropped]\n{summary_text}"
                    ),
                    pinned=True,
                )
            )
        new_messages.extend(recent)

        after = self.total_tokens(new_messages)
        return CompactionResult(
            messages=new_messages,
            compacted=True,
            summary=summary_text,
            tokens_before=before,
            tokens_after=after,
            dropped=len(older),
        )


class Notebook:
    """Durable structured notes for a loop — memory that outlives the transcript.

    Backed by the loop's section in the :class:`~loopengine.state.StateStore`
    (under a ``notes`` key), so notes survive both compaction and process exit.
    Writes are read-modify-write on the section so other keys are preserved.
    """

    KEY = "notes"

    def __init__(self, state, loop_id: str) -> None:
        self.state = state
        self.loop_id = loop_id

    def notes(self) -> list[str]:
        section = self.state.read_section(self.loop_id)
        return list(section.get(self.KEY, []))

    def add(self, note: str) -> None:
        note = note.strip()
        if not note:
            return
        section = self.state.read_section(self.loop_id)
        notes = list(section.get(self.KEY, []))
        notes.append(note)
        section[self.KEY] = notes
        self.state.write_section(self.loop_id, section)

    def clear(self) -> None:
        section = self.state.read_section(self.loop_id)
        if self.KEY in section:
            section.pop(self.KEY)
            self.state.write_section(self.loop_id, section)
