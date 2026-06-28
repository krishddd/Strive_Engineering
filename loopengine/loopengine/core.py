"""Thin Python boundary to the Rust ``loopguard`` core.

Integration is by subprocess + JSON rather than FFI: the runtime calls the
``loopguard`` binary and parses its stdout. This keeps the language boundary
explicit and build-simple (no maturin/linking step), while all
constraint-critical logic stays in the tested Rust core.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Sequence


class LoopguardUnavailable(RuntimeError):
    """Raised when the loopguard binary cannot be located."""


# Exit codes are a stable contract with crates/loopguard/src/main.rs.
EXIT_OK = 0
EXIT_BLOCKED = 2
EXIT_FABRICATED = 3
EXIT_UNVERIFIABLE = 4
EXIT_TAMPERED = 5
EXIT_INJECTION = 6


def _candidate_paths() -> list[Path]:
    here = Path(__file__).resolve()
    root = here.parents[2]  # repo root: .../Strive_Engineering
    exe = "loopguard.exe" if os.name == "nt" else "loopguard"
    return [
        root / "target" / "release" / exe,
        root / "target" / "debug" / exe,
    ]


def find_loopguard(explicit: str | None = None) -> str:
    """Locate the loopguard binary: explicit path, env var, build dir, or PATH."""
    if explicit:
        if Path(explicit).exists():
            return explicit
        raise LoopguardUnavailable(f"loopguard not found at {explicit!r}")
    env = os.environ.get("LOOPGUARD_BIN")
    if env and Path(env).exists():
        return env
    for path in _candidate_paths():
        if path.exists():
            return str(path)
    on_path = shutil.which("loopguard")
    if on_path:
        return on_path
    raise LoopguardUnavailable(
        "loopguard binary not found. Build it with `cargo build --release` "
        "or set LOOPGUARD_BIN to its path."
    )


@dataclass
class GuardDecision:
    allowed: bool
    rule: str | None
    reason: str | None


class Loopguard:
    """Wrapper over the loopguard CLI."""

    def __init__(self, binary: str | None = None) -> None:
        self.binary = find_loopguard(binary)

    def _run(self, args: Sequence[str]) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [self.binary, *args],
            capture_output=True,
            text=True,
            check=False,
        )

    def check_command(self, command: str) -> GuardDecision:
        """Evaluate a shell command against the deterministic denylist guard."""
        proc = self._run(["check-command", command])
        data = json.loads(proc.stdout or "{}")
        if data.get("decision") == "block":
            return GuardDecision(False, data.get("rule"), data.get("reason"))
        return GuardDecision(True, None, None)

    def scan_diff(self, diff_text: str) -> dict:
        """Scan a unified diff for verifier-tampering (reward-hacking) moves.

        Returns ``{"clean": bool, "findings": [...]}``. The runtime escalates a
        proposed L2 change whenever ``clean`` is False.
        """
        proc = subprocess.run(
            [self.binary, "scan-diff", "-"],
            input=diff_text,
            capture_output=True,
            text=True,
            check=False,
        )
        return json.loads(proc.stdout or '{"clean":true,"findings":[]}')

    def scan_injection(self, text: str) -> dict:
        """Scan untrusted tool-return text for prompt-injection signatures.

        Returns ``{"severity": "none|low|medium|high", "signals": [...]}``.
        """
        proc = subprocess.run(
            [self.binary, "scan-injection", "-"],
            input=text,
            capture_output=True,
            text=True,
            check=False,
        )
        return json.loads(proc.stdout or '{"severity":"none","signals":[]}')

    def verify_shas(self, repo: str, shas: Sequence[str]) -> dict:
        """Grounded verification: do these commit SHAs resolve in ``repo``?

        Returns the parsed batch result: ``{"valid": bool, "claims": [...]}``.
        Distinguishes fabricated (exit 3) from unverifiable (exit 4) via the
        ``unverifiable`` flag so callers can escalate the latter rather than
        treat it as a clean pass.
        """
        if not shas:
            return {"valid": True, "claims": [], "unverifiable": False}
        proc = self._run(["verify-sha", repo, *shas])
        data = json.loads(proc.stdout or '{"valid":false,"claims":[]}')
        data["unverifiable"] = proc.returncode == EXIT_UNVERIFIABLE
        return data
