"""Agent makers — the step where the loop actually *prompts an agent*.

Everything else in this repo is the harness around the agent: the trigger, the
isolation, the verifier, the brakes. The maker is the agent itself — it reads the
task (plus the worktree's current state and the checker's prior reflections) and
proposes file edits. The AssistedFixLoop then gates that proposal through the
integrity scanner and the test command, and on failure feeds a reflection back
here (Reflexion).

The LLM call is isolated behind an ``LLMClient`` protocol so the maker is
deterministically testable with a fake client and has no hard dependency on the
``anthropic`` SDK unless you actually use the LLM maker.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Protocol

# Default to the latest, most capable Claude model. (Claude API reference: use
# claude-opus-4-8 unless the user names another model.)
DEFAULT_MODEL = "claude-opus-4-8"

# Structured-output schema: the model must return a list of files to write.
_FILES_SCHEMA = {
    "type": "object",
    "properties": {
        "files": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "path": {"type": "string"},
                    "content": {"type": "string"},
                },
                "required": ["path", "content"],
                "additionalProperties": False,
            },
        }
    },
    "required": ["files"],
    "additionalProperties": False,
}

SYSTEM_PROMPT = (
    "You are an implementer agent inside an automated assisted-fix loop. You are given a "
    "task, a snapshot of the current repository files, and (after a failed attempt) the "
    "verifier's reflections on why the last attempt failed. Propose the minimal set of file "
    "writes that makes the task's test command pass.\n\n"
    "Hard rules:\n"
    "- Return COMPLETE file contents for every file you change, not a diff.\n"
    "- Fix the actual code. NEVER delete a test, weaken or remove an assertion, add a skip/"
    "ignore marker, or edit the test/eval harness to force a pass — an integrity scanner will "
    "catch that and the run will be rejected.\n"
    "- Make the smallest change that addresses the task."
)


class LLMClient(Protocol):
    """Minimal text-in/JSON-out interface the maker depends on."""

    def complete_json(self, system: str, user: str, schema: dict) -> dict: ...


class AnthropicClient:
    """LLMClient backed by the Anthropic SDK (Claude). Lazy-imports ``anthropic``
    so it's only required when the LLM maker is actually used."""

    def __init__(self, model: str = DEFAULT_MODEL, max_tokens: int = 16000) -> None:
        self.model = model
        self.max_tokens = max_tokens

    def complete_json(self, system: str, user: str, schema: dict) -> dict:
        import anthropic  # lazy — keeps the base install SDK-free

        client = anthropic.Anthropic()  # reads ANTHROPIC_API_KEY from the env
        resp = client.messages.create(
            model=self.model,
            max_tokens=self.max_tokens,
            system=system,
            messages=[{"role": "user", "content": user}],
            output_config={"format": {"type": "json_schema", "schema": schema}},
        )
        text = next((b.text for b in resp.content if b.type == "text"), "")
        return json.loads(text)


class LLMMaker:
    """A maker that prompts an LLM agent to produce file edits, then writes them
    into the worktree. Conforms to the AssistedFixLoop maker signature."""

    def __init__(self, client: LLMClient, max_snapshot_bytes: int = 20000) -> None:
        self.client = client
        self.max_snapshot_bytes = max_snapshot_bytes

    def __call__(self, worktree_path: Path, task: str, reflections: list[str]) -> None:
        snapshot = self._snapshot(worktree_path)
        user = self._build_prompt(task, snapshot, reflections)
        result = self.client.complete_json(SYSTEM_PROMPT, user, _FILES_SCHEMA)
        for f in result.get("files", []):
            self._write(worktree_path, f["path"], f["content"])

    # -- helpers ------------------------------------------------------------

    def _snapshot(self, root: Path) -> str:
        """A bounded text snapshot of the worktree for the model's context."""
        parts: list[str] = []
        budget = self.max_snapshot_bytes
        for p in sorted(root.rglob("*")):
            if not p.is_file() or ".git" in p.parts:
                continue
            try:
                text = p.read_text(encoding="utf-8")
            except (UnicodeDecodeError, OSError):
                continue  # skip binaries / unreadable
            rel = p.relative_to(root).as_posix()
            block = f"--- {rel} ---\n{text}\n"
            if len(block) > budget:
                break
            budget -= len(block)
            parts.append(block)
        return "".join(parts)

    def _build_prompt(self, task: str, snapshot: str, reflections: list[str]) -> str:
        out = [f"TASK:\n{task}\n", f"CURRENT FILES:\n{snapshot}"]
        if reflections:
            out.append("PRIOR ATTEMPTS FAILED — reflections:\n" + "\n".join(reflections))
        out.append("Return the files to write so the test command passes.")
        return "\n\n".join(out)

    def _write(self, root: Path, rel_path: str, content: str) -> None:
        # Confine writes to the worktree (no path traversal — the model's path is untrusted).
        target = (root / rel_path).resolve()
        root_resolved = root.resolve()
        if not str(target).startswith(str(root_resolved)):
            raise ValueError(f"refusing to write outside the worktree: {rel_path}")
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding="utf-8")


def make_maker(cfg: dict):
    """Build a maker from a spec's ``maker`` config block.

    ``{"type": "llm", "model": "claude-opus-4-8"}`` → an LLMMaker backed by Claude.
    """
    kind = cfg.get("type")
    if kind == "llm":
        return LLMMaker(AnthropicClient(model=cfg.get("model", DEFAULT_MODEL)))
    raise ValueError(f"unknown maker type: {kind!r}")
