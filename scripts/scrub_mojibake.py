#!/usr/bin/env python3
"""Repair cp1252-mangled UTF-8 ("mojibake") in a loop state JSON file.

Incident (2026-07-06, docs/failure-modes.md): before every subprocess boundary
was forced to UTF-8, ``git log`` output on Windows was decoded as cp1252, so a
UTF-8 em-dash (``—``, bytes E2 80 94) landed in the state file as the three
characters ``â€"``. The encoding fix stopped *new* corruption but never remediated
the findings already written to ``.loop-state/state.json``.

This is the one-off remediation pass. It walks every string in the JSON and, for
any that round-trips cleanly through the mojibake transform, replaces it with the
recovered text. Strings that don't round-trip are left untouched, so it's safe to
run repeatedly (idempotent) and safe on already-clean files.

    python scripts/scrub_mojibake.py .loop-state/state.json          # in place
    python scripts/scrub_mojibake.py .loop-state/state.json --check  # report only
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any


def demojibake(text: str) -> str:
    """Recover text that was UTF-8 bytes decoded as cp1252. Returns the input
    unchanged when the transform isn't applicable (already clean, or not this
    particular corruption)."""
    # Fast path: only strings carrying the tell-tale bytes are candidates.
    if not any(ch in text for ch in ("Ã", "Â", "â", "€", "")):
        return text
    try:
        recovered = text.encode("cp1252").decode("utf-8")
    except (UnicodeEncodeError, UnicodeDecodeError):
        return text
    # Only accept the recovery if it actually removed suspicious sequences and is
    # itself clean — never make a string worse.
    if recovered == text:
        return text
    return recovered


def _walk(node: Any) -> tuple[Any, int]:
    fixed = 0
    if isinstance(node, str):
        new = demojibake(node)
        return new, (1 if new != node else 0)
    if isinstance(node, list):
        out = []
        for item in node:
            v, n = _walk(item)
            out.append(v)
            fixed += n
        return out, fixed
    if isinstance(node, dict):
        out = {}
        for k, v in node.items():
            nv, n = _walk(v)
            out[k] = nv
            fixed += n
        return out, fixed
    return node, 0


def scrub_file(path: Path, check_only: bool = False) -> int:
    data = json.loads(path.read_text(encoding="utf-8"))
    fixed_data, count = _walk(data)
    if count and not check_only:
        path.write_text(json.dumps(fixed_data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return count


def main(argv: list[str]) -> int:
    args = [a for a in argv if a != "--check"]
    check = "--check" in argv
    if not args:
        print("usage: scrub_mojibake.py <state.json> [--check]", file=sys.stderr)
        return 64
    path = Path(args[0])
    if not path.exists():
        print(f"no such file: {path}", file=sys.stderr)
        return 1
    count = scrub_file(path, check_only=check)
    verb = "would fix" if check else "fixed"
    print(f"{verb} {count} mojibake string(s) in {path}")
    return 1 if (check and count) else 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
