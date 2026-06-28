"""Validate loop specs against the JSON Schema before running them.

A malformed spec should fail loudly at load time, not midway through a run with a
confusing KeyError. The schema lives at ``schemas/loop.schema.json`` and is the
single source of truth for a loop's shape.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any


class SpecInvalid(ValueError):
    """A loop spec does not conform to schemas/loop.schema.json."""


def _schema_path() -> Path:
    # repo root: .../Strive_Engineering ; this file: loopengine/loopengine/validate.py
    return Path(__file__).resolve().parents[2] / "schemas" / "loop.schema.json"


def load_schema() -> dict[str, Any]:
    return json.loads(_schema_path().read_text(encoding="utf-8"))


def validate_spec(spec: dict[str, Any]) -> None:
    """Raise SpecInvalid if ``spec`` violates the schema. No-op if jsonschema
    is unavailable (validation is a guardrail, not a hard dependency of running)."""
    try:
        import jsonschema
    except ImportError:  # pragma: no cover - environment without the optional dep
        return
    try:
        jsonschema.validate(instance=spec, schema=load_schema())
    except jsonschema.ValidationError as e:  # type: ignore[attr-defined]
        path = "/".join(str(p) for p in e.absolute_path) or "<root>"
        raise SpecInvalid(f"invalid loop spec at {path}: {e.message}") from None
