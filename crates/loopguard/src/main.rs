//! `loopguard` CLI — the JSON-emitting boundary the Python runtime calls.
//!
//! Subcommands:
//!   loopguard check-command "<cmd>"       -> {"decision":"allow"|"block",...}; exit 2 on block
//!   loopguard verify-sha <repo> <sha>...  -> batch verdict JSON; exit 3/4 on failure
//!   loopguard verify-iso <repo> <sha>...  -> isomorphic batch JSON; exit 8 on a gap
//!   loopguard budget [--max-tokens N] ... -> normalized budget JSON
//!   loopguard scan-diff [file|-]          -> integrity report JSON; exit 5 if tampering
//!   loopguard scan-injection [file|-]     -> injection report JSON; exit 6 if high severity
//!   loopguard check-allowlist <policy> [diff|-] -> policy decision JSON; exit 7 if escalate
//!
//! Stable exit codes (a contract with the Python runtime):
//!   0 = ok/allow/clean/auto-ok, 2 = command blocked, 3 = a claim was fabricated,
//!   4 = verifier could not run (escalate), 5 = diff tampers with the verifier,
//!   6 = high-severity prompt injection in untrusted text,
//!   7 = change is not auto-mergeable under the L3 allowlist (escalate to human),
//!   8 = isomorphic-perturbation gap (a verifier shortcut; escalate to human).
//!
//! Arg parsing is hand-rolled deliberately: it keeps the dependency graph to
//! pure-Rust crates so the binary links cleanly under the self-contained
//! windows-gnu toolchain (no dlltool / external MinGW required).

use loopguard::{verify_batch, verify_batch_isomorphic, Budget, Guard};

fn usage() -> ! {
    eprintln!(
        "usage:\n  loopguard check-command \"<cmd>\"\n  loopguard verify-sha <repo> <sha>...\n  loopguard verify-iso <repo> <sha>...\n  loopguard budget [--max-tokens N] [--max-iterations N] [--wall-clock-secs N]"
    );
    std::process::exit(64);
}

fn main() {
    let args: Vec<String> = std::env::args().skip(1).collect();
    let Some(sub) = args.first() else { usage() };

    match sub.as_str() {
        "check-command" => {
            let command = args.get(1).unwrap_or_else(|| usage());
            let decision = Guard::default().check(command);
            println!("{}", serde_json::to_string(&decision).unwrap());
            if decision.is_block() {
                std::process::exit(2);
            }
        }
        "verify-sha" => {
            let repo = args.get(1).unwrap_or_else(|| usage());
            let shas: Vec<String> = args[2..].to_vec();
            if shas.is_empty() {
                usage();
            }
            let result = verify_batch(repo, &shas);
            println!("{}", serde_json::to_string(&result).unwrap());
            if !result.valid {
                let unverifiable = result
                    .claims
                    .iter()
                    .any(|c| matches!(c.verdict, loopguard::Verdict::Unverifiable { .. }));
                std::process::exit(if unverifiable { 4 } else { 3 });
            }
        }
        "verify-iso" => {
            let repo = args.get(1).unwrap_or_else(|| usage());
            let shas: Vec<String> = args[2..].to_vec();
            if shas.is_empty() {
                usage();
            }
            let result = verify_batch_isomorphic(repo, &shas);
            println!("{}", serde_json::to_string(&result).unwrap());
            if result.unverifiable {
                std::process::exit(4); // could not run the check → escalate
            }
            if !result.consistent {
                std::process::exit(8); // literal/isomorphic gap → verifier shortcut
            }
        }
        "budget" => {
            let mut max_tokens = None;
            let mut max_iterations = None;
            let mut wall_clock_secs = None;
            let mut i = 1;
            while i < args.len() {
                let flag = &args[i];
                let val = args.get(i + 1).and_then(|v| v.parse::<u64>().ok());
                match flag.as_str() {
                    "--max-tokens" => max_tokens = val,
                    "--max-iterations" => max_iterations = val.map(|v| v as u32),
                    "--wall-clock-secs" => wall_clock_secs = val,
                    _ => usage(),
                }
                i += 2;
            }
            let b = Budget::new(max_tokens, max_iterations, wall_clock_secs);
            println!("{}", serde_json::to_string(&b).unwrap());
        }
        "scan-diff" => {
            let text = read_input(args.get(1).map(String::as_str));
            let report = loopguard::scan_diff(&text);
            println!("{}", serde_json::to_string(&report).unwrap());
            if !report.clean {
                std::process::exit(5);
            }
        }
        "scan-injection" => {
            let text = read_input(args.get(1).map(String::as_str));
            let report = loopguard::scan_injection(&text);
            println!("{}", serde_json::to_string(&report).unwrap());
            if report.severity >= loopguard::Severity::High {
                std::process::exit(6);
            }
        }
        "check-allowlist" => {
            let policy_path = args.get(1).unwrap_or_else(|| usage());
            let policy_json = std::fs::read_to_string(policy_path).unwrap_or_else(|e| {
                eprintln!("cannot read policy {policy_path}: {e}");
                std::process::exit(64);
            });
            let policy: loopguard::AllowPolicy =
                serde_json::from_str(&policy_json).unwrap_or_else(|e| {
                    eprintln!("invalid policy JSON: {e}");
                    std::process::exit(64);
                });
            let diff = read_input(args.get(2).map(String::as_str));
            let decision = loopguard::evaluate_policy(&diff, &policy);
            println!("{}", serde_json::to_string(&decision).unwrap());
            if !decision.auto_ok {
                std::process::exit(7);
            }
        }
        "-h" | "--help" | "help" => usage(),
        _ => usage(),
    }
}

/// Read scan input from a file path, or from stdin when the arg is "-" or absent.
fn read_input(arg: Option<&str>) -> String {
    use std::io::Read;
    match arg {
        Some(path) if path != "-" => std::fs::read_to_string(path).unwrap_or_else(|e| {
            eprintln!("cannot read {path}: {e}");
            std::process::exit(64);
        }),
        _ => {
            let mut buf = String::new();
            std::io::stdin().read_to_string(&mut buf).ok();
            buf
        }
    }
}
