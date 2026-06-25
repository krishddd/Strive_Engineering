"""External, durable state — the loop's memory spine.

State is JSON on disk (machine-readable, schema-checkable) plus an append-only
run log. A loop reads its section at the start of a run and overwrites only that
section at the end. The run log is never edited, only appended — it is the audit
trail you reconstruct history from when something goes wrong.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any


class StateStore:
    """A JSON state file keyed by loop id, plus a JSONL run log alongside it."""

    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)
        self.runlog_path = self.path.with_name(self.path.stem + ".runlog.jsonl")

    def _load(self) -> dict[str, Any]:
        if not self.path.exists():
            return {"version": 1, "loops": {}}
        return json.loads(self.path.read_text(encoding="utf-8"))

    def read_section(self, loop_id: str) -> dict[str, Any]:
        """Return the loop's section, or an empty dict if it has never run."""
        return self._load().get("loops", {}).get(loop_id, {})

    def write_section(self, loop_id: str, section: dict[str, Any]) -> None:
        """Overwrite only this loop's section; leave others untouched."""
        data = self._load()
        data.setdefault("loops", {})[loop_id] = section
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")

    def append_runlog(self, row: dict[str, Any]) -> None:
        """Append one immutable run-log row (JSONL)."""
        self.runlog_path.parent.mkdir(parents=True, exist_ok=True)
        with self.runlog_path.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(row) + "\n")
