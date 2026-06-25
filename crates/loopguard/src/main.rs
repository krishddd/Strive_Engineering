//! `loopguard` CLI — the JSON-emitting boundary the Python runtime calls.
//!
//! Subcommands:
//!   loopguard check-command "<cmd>"       -> {"decision":"allow"|"block",...}; exit 2 on block
//!   loopguard verify-sha <repo> <sha>...  -> batch verdict JSON; exit 3/4 on failure
//!   loopguard budget [--max-tokens N] ... -> normalized budget JSON
//!
//! Stable exit codes (a contract with the Python runtime):
//!   0 = ok/allow/all-grounded, 2 = command blocked, 3 = a claim was fabricated,
//!   4 = verifier could not run (escalate).
//!
//! Arg parsing is hand-rolled deliberately: it keeps the dependency graph to
//! pure-Rust crates so the binary links cleanly under the self-contained
//! windows-gnu toolchain (no dlltool / external MinGW required).

use loopguard::{verify_batch, Budget, Guard};

fn usage() -> ! {
    eprintln!(
        "usage:\n  loopguard check-command \"<cmd>\"\n  loopguard verify-sha <repo> <sha>...\n  loopguard budget [--max-tokens N] [--max-iterations N] [--wall-clock-secs N]"
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
        "-h" | "--help" | "help" => usage(),
        _ => usage(),
    }
}
