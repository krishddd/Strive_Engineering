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


def cmd_verify_iso(args: argparse.Namespace) -> int:
    r = Loopguard().verify_isomorphic(args.repo, args.shas)
    print(json.dumps(r))
    if r.get("unverifiable"):
        print("ESCALATE: verifier could not run on every claim", file=sys.stderr)
        return 4
    if r.get("gap"):
        print("ESCALATE: isomorphic gap — a claim passed one check but not its equivalent", file=sys.stderr)
        return 8
    return 0


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
        warn = f" ⚠ {it.anomaly}" if it.anomaly else ""
        print(f"  {mark} {it.loop_id}: {it.result or it.reason}{warn}{bell}")
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


def cmd_init(args: argparse.Namespace) -> int:
    from .authoring import scaffold_spec

    try:
        spec = scaffold_spec(args.id, args.kind)
    except ValueError as e:
        print(f"error: {e}", file=sys.stderr)
        return 64
    text = json.dumps(spec, indent=2) + "\n"
    if args.out and args.out != "-":
        out = Path(args.out)
        if out.exists() and not args.force:
            print(f"refusing to overwrite {out} (pass --force)", file=sys.stderr)
            return 1
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(text, encoding="utf-8")
        print(f"wrote {out} — edit target.repo, then `loopengine audit {out}`")
    else:
        print(text, end="")
    return 0


def cmd_cost(args: argparse.Namespace) -> int:
    from .authoring import estimate_cost

    est = estimate_cost(_load_spec(args.spec))
    print(json.dumps(est.as_dict(), indent=2))
    # Non-zero only when the per-run estimate already blows the configured cap.
    return 1 if est.within_budget is False else 0


def cmd_audit(args: argparse.Namespace) -> int:
    from .authoring import audit_spec

    report = audit_spec(_load_spec(args.spec))
    if args.json:
        print(json.dumps(report.as_dict(), indent=2))
    else:
        print(f"{report.loop_id} [{report.kind}] — score {report.score}/100")
        print(f"  declares {report.declared_phase}, structurally ready for {report.ready_for}")
        for c in report.checks:
            print(f"  [{'x' if c.ok else ' '}] {c.name}: {c.detail}")
        for s in report.suggestions:
            print(f"  → {s}")
    # Non-zero when the spec can't even support its declared phase.
    from .authoring import _phase_rank

    ok = _phase_rank(report.ready_for) >= _phase_rank(report.declared_phase)
    return 0 if ok else 1


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

    pvi = sub.add_parser("verify-iso", help="isomorphic-perturbation SHA verification (anti-reward-hacking)")
    pvi.add_argument("repo")
    pvi.add_argument("shas", nargs="+")
    pvi.set_defaults(func=cmd_verify_iso)

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

    pin = sub.add_parser("init", help="scaffold a schema-valid starter loop spec")
    pin.add_argument("id", help="loop id")
    pin.add_argument("--kind", default="git-commit-triage", choices=["git-commit-triage", "assisted-fix"])
    pin.add_argument("--out", help="write to this path (default: stdout)")
    pin.add_argument("--force", action="store_true", help="overwrite an existing file")
    pin.set_defaults(func=cmd_init)

    pco = sub.add_parser("cost", help="estimate per-run / per-day token spend for a loop spec")
    pco.add_argument("spec", help="path to a loop spec JSON")
    pco.set_defaults(func=cmd_cost)

    pau = sub.add_parser("audit", help="score a loop spec's readiness across the L0→L3 ladder")
    pau.add_argument("spec", help="path to a loop spec JSON")
    pau.add_argument("--json", action="store_true", help="emit the full report as JSON")
    pau.set_defaults(func=cmd_audit)

    return p


def main(argv: list[str] | None = None) -> int:
    # Print UTF-8 regardless of the console code page so glyphs in the schedule
    # output don't crash on a Windows cp1252 terminal.
    try:
        sys.stdout.reconfigure(encoding="utf-8")  # type: ignore[union-attr]
    except (AttributeError, ValueError):  # pragma: no cover - non-reconfigurable stream
        pass
    args = build_parser().parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
