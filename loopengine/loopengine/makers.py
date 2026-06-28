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

# NVIDIA NIM: free, OpenAI-compatible endpoint (key prefix nvapi-, ~40 req/min).
# Default to a model that supports structured output and reliable JSON.
NVIDIA_BASE_URL = "https://integrate.api.nvidia.com/v1"
DEFAULT_NVIDIA_MODEL = "meta/llama-3.3-70b-instruct"

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


def _extract_json(text: str) -> dict:
    """Pull a JSON object out of a model response — robust to code fences, prose
    preambles, and reasoning models that emit <think> blocks before the JSON."""
    import re as _re

    t = _re.sub(r"<think>.*?</think>", "", text, flags=_re.DOTALL).strip()
    # Strip a ```json ... ``` fence if present.
    fence = _re.search(r"```(?:json)?\s*(\{.*?\})\s*```", t, flags=_re.DOTALL)
    if fence:
        return json.loads(fence.group(1))
    # Otherwise scan for the first balanced top-level {...}.
    start = t.find("{")
    if start == -1:
        raise ValueError("no JSON object found in model response")
    depth = 0
    in_str = False
    esc = False
    for i in range(start, len(t)):
        c = t[i]
        if in_str:
            if esc:
                esc = False
            elif c == "\\":
                esc = True
            elif c == '"':
                in_str = False
        elif c == '"':
            in_str = True
        elif c == "{":
            depth += 1
        elif c == "}":
            depth -= 1
            if depth == 0:
                return json.loads(t[start : i + 1])
    raise ValueError("unbalanced JSON object in model response")


class OpenAICompatibleClient:
    """LLMClient for any OpenAI-compatible /v1/chat/completions endpoint — most
    usefully NVIDIA NIM's free tier (build.nvidia.com). Uses only the standard
    library (urllib), so there is no SDK dependency. The HTTP call is isolated in
    ``transport`` so the client is testable without a network or key.
    """

    def __init__(
        self,
        model: str,
        base_url: str = NVIDIA_BASE_URL,
        api_key_env: str = "NVIDIA_API_KEY",
        max_tokens: int = 8000,
        transport=None,
    ) -> None:
        self.model = model
        self.base_url = base_url.rstrip("/")
        self.api_key_env = api_key_env
        self.max_tokens = max_tokens
        self.transport = transport or self._http_transport

    def complete_json(self, system: str, user: str, schema: dict) -> dict:
        user_with_schema = (
            f"{user}\n\nRespond with ONLY a single JSON object matching this schema "
            f"(no prose, no code fence):\n{json.dumps(schema)}"
        )
        import urllib.error

        payload = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user_with_schema},
            ],
            "temperature": 0.2,
            "max_tokens": self.max_tokens,
            "response_format": {"type": "json_object"},
        }
        try:
            content = self.transport(payload)
        except urllib.error.HTTPError as e:
            if e.code != 400:
                raise
            # Some free NIM models reject response_format — retry without it.
            # The prompt still demands JSON and _extract_json is forgiving.
            payload.pop("response_format", None)
            content = self.transport(payload)
        return _extract_json(content)

    def _http_transport(self, payload: dict) -> str:
        import os
        import urllib.request

        key = os.environ.get(self.api_key_env)
        if not key:
            raise RuntimeError(f"{self.api_key_env} is not set (get a free key at build.nvidia.com)")
        req = urllib.request.Request(
            f"{self.base_url}/chat/completions",
            data=json.dumps(payload).encode("utf-8"),
            headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=120) as resp:  # noqa: S310 — fixed https endpoint
            data = json.loads(resp.read().decode("utf-8"))
        return data["choices"][0]["message"]["content"]


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

    - ``{"type": "llm", "model": "claude-opus-4-8"}`` → Claude (Anthropic).
    - ``{"type": "nvidia", "model": "meta/llama-3.3-70b-instruct"}`` → NVIDIA NIM
      free tier (set NVIDIA_API_KEY).
    - ``{"type": "openai", "base_url": "...", "model": "...", "api_key_env": "..."}``
      → any OpenAI-compatible endpoint.
    """
    kind = cfg.get("type")
    if kind == "llm":
        return LLMMaker(AnthropicClient(model=cfg.get("model", DEFAULT_MODEL)))
    if kind == "nvidia":
        return LLMMaker(
            OpenAICompatibleClient(
                model=cfg.get("model", DEFAULT_NVIDIA_MODEL),
                base_url=cfg.get("base_url", NVIDIA_BASE_URL),
                api_key_env=cfg.get("api_key_env", "NVIDIA_API_KEY"),
            )
        )
    if kind == "openai":
        base_url = cfg.get("base_url")
        if not base_url:
            raise ValueError("openai maker requires a base_url")
        if "model" not in cfg:
            raise ValueError("openai maker requires a model")
        return LLMMaker(
            OpenAICompatibleClient(
                model=cfg["model"],
                base_url=base_url,
                api_key_env=cfg.get("api_key_env", "OPENAI_API_KEY"),
            )
        )
    raise ValueError(f"unknown maker type: {kind!r}")
