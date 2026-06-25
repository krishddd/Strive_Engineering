"""``loopengine`` command-line entry point."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from .core import Loopguard, LoopguardUnavailable
from .runtime import LoopRuntime
from .state import StateStore
from .verifier import VerificationError, Verifier


def _load_spec(path: str) -> dict:
    return json.loads(Path(path).read_text(encoding="utf-8"))


def cmd_run(args: argparse.Namespace) -> int:
    spec = _load_spec(args.spec)
    state = StateStore(args.state or spec.get("state_file", ".loop-state/state.json"))
    try:
        runtime = LoopRuntime(spec, state)
    except LoopguardUnavailable as e:
        print(f"error: {e}", file=sys.stderr)
        return 4
    res = runtime.run()
    high = [f for f in res.findings if f.bucket == "high"]
    watch = [f for f in res.findings if f.bucket == "watch"]
    print(f"[{res.result}] {spec['id']}: {len(high)} high, {len(watch)} watch — {res.note or 'ok'}")
    for f in high:
        print(f"  HIGH  {f.text} ({f.sha})")
    for f in watch:
        print(f"  watch {f.text} ({f.sha})")
    return 0 if res.result in ("clean", "found") else 1


def cmd_guard(args: argparse.Namespace) -> int:
    d = Loopguard().check_command(args.command)
    if d.allowed:
        print("allow")
        return 0
    print(f"BLOCK [{d.rule}]: {d.reason}", file=sys.stderr)
    return 2


def cmd_verify(args: argparse.Namespace) -> int:
    try:
        r = Verifier().verify_commit_claims(args.repo, args.shas)
    except VerificationError as e:
        print(f"ESCALATE: {e}", file=sys.stderr)
        return 4
    print(json.dumps({"valid": r.valid, "grounded": r.grounded, "fabricated": r.fabricated}))
    return 0 if r.valid else 3


def cmd_show(args: argparse.Namespace) -> int:
    section = StateStore(args.state).read_section(args.loop_id)
    print(json.dumps(section, indent=2))
    return 0


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="loopengine", description="Loop-engineering runtime")
    sub = p.add_subparsers(dest="cmd", required=True)

    pr = sub.add_parser("run", help="run one cycle of a loop spec")
    pr.add_argument("spec", help="path to a loop spec JSON")
    pr.add_argument("--state", help="override the state file path")
    pr.set_defaults(func=cmd_run)

    pg = sub.add_parser("guard", help="check a shell command against the denylist")
    pg.add_argument("command")
    pg.set_defaults(func=cmd_guard)

    pv = sub.add_parser("verify", help="grounded SHA verification against a repo")
    pv.add_argument("repo")
    pv.add_argument("shas", nargs="+")
    pv.set_defaults(func=cmd_verify)

    ps = sub.add_parser("show", help="print a loop's current state section")
    ps.add_argument("state")
    ps.add_argument("loop_id")
    ps.set_defaults(func=cmd_show)

    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
