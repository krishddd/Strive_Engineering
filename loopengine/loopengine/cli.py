"""``loopengine`` command-line entry point."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from .core import Loopguard, LoopguardUnavailable
from .runtime import LoopRuntime
from .state import StateStore
from .validate import SpecInvalid, validate_spec
from .verifier import VerificationError, Verifier


def _load_spec(path: str) -> dict:
    return json.loads(Path(path).read_text(encoding="utf-8"))


def cmd_run(args: argparse.Namespace) -> int:
    spec = _load_spec(args.spec)
    try:
        validate_spec(spec)
    except SpecInvalid as e:
        print(f"error: {e}", file=sys.stderr)
        return 64
    state = StateStore(args.state or spec.get("state_file", ".loop-state/state.json"))
    try:
        if spec.get("kind") == "assisted-fix":
            from .assisted import AssistedFixLoop
            from .makers import make_maker

            maker = make_maker(spec["maker"]) if spec.get("maker") else None
            res = AssistedFixLoop(spec, state, maker=maker).run()
            print(f"[{res.result}] {spec['id']}: {res.attempts} attempt(s) — {res.note}")
            if res.branch:
                print(f"  branch for review: {res.branch} @ {res.commit}")
            for r in res.reflections:
                print(f"  reflection: {r}")
            return 0 if res.result == "proposed" else 1

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


def cmd_scan_diff(args: argparse.Namespace) -> int:
    text = Path(args.file).read_text(encoding="utf-8") if args.file != "-" else sys.stdin.read()
    report = Loopguard().scan_diff(text)
    print(json.dumps(report, indent=2))
    return 0 if report.get("clean") else 5


def cmd_scan_injection(args: argparse.Namespace) -> int:
    text = Path(args.file).read_text(encoding="utf-8") if args.file != "-" else sys.stdin.read()
    report = Loopguard().scan_injection(text)
    print(json.dumps(report, indent=2))
    return 6 if report.get("severity") == "high" else 0


def cmd_schedule(args: argparse.Namespace) -> int:
    import datetime as _dt

    from .scheduler import Scheduler

    paths = sorted(Path(args.dir).glob("*.json")) if Path(args.dir).is_dir() else [Path(args.dir)]
    specs = []
    for p in paths:
        spec = _load_spec(str(p))
        try:
            validate_spec(spec)
        except SpecInvalid as e:
            print(f"skipping {p.name}: {e}", file=sys.stderr)
            continue
        specs.append(spec)
    if not specs:
        print("no valid loop specs found", file=sys.stderr)
        return 1
    state = StateStore(args.state)
    now = args.now or _dt.datetime.now(_dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    summary = Scheduler(state).run_once(specs, now)
    for it in summary.items:
        mark = "•" if it.ran else "-"
        bell = " 🔔" if it.notify else ""
        print(f"  {mark} {it.loop_id}: {it.result or it.reason}{bell}")
    print(f"[tick {now}] {len(summary.notifications)} notification(s)")
    return 0


def cmd_serve(args: argparse.Namespace) -> int:
    from .dashboard_api import serve

    serve(args.state, port=args.port)
    return 0


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

    pd = sub.add_parser("scan-diff", help="flag verifier-tampering moves in a unified diff")
    pd.add_argument("file", nargs="?", default="-", help="diff file, or - for stdin")
    pd.set_defaults(func=cmd_scan_diff)

    pi = sub.add_parser("scan-injection", help="scan untrusted text for prompt injection")
    pi.add_argument("file", nargs="?", default="-", help="text file, or - for stdin")
    pi.set_defaults(func=cmd_scan_injection)

    ps = sub.add_parser("show", help="print a loop's current state section")
    ps.add_argument("state")
    ps.add_argument("loop_id")
    ps.set_defaults(func=cmd_show)

    psc = sub.add_parser("schedule", help="run all due loops in a directory once (one tick)")
    psc.add_argument("dir", help="directory of loop spec JSONs (or a single spec file)")
    psc.add_argument("--state", default=".loop-state/state.json")
    psc.add_argument("--now", help="ISO8601 UTC override (default: now)")
    psc.set_defaults(func=cmd_schedule)

    psv = sub.add_parser("serve", help="serve the read-only dashboard + JSON API")
    psv.add_argument("--state", default=".loop-state/state.json")
    psv.add_argument("--port", type=int, default=8765)
    psv.set_defaults(func=cmd_serve)

    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
