//! Port of grund.318's root/worldsim/tractor1 reproducer (§FS-workspace.8.1.3).
//! The member stays local; only verified configuration earns a root retry.

use std::fs;
use std::io::Write;
use std::path::{Path, PathBuf};
use std::process::{Command, Output, Stdio};
use std::sync::atomic::{AtomicU64, Ordering};

use serde_json::{Value, json};

const ID: &str = "tractor1/DA-001-tier1-purpose-built-vehicle";
const GENERIC: &str =
    "note: workspace aliases are defined in the root grund.toml under [workspace]";

struct Workspace(PathBuf);

impl Workspace {
    fn new() -> Self {
        static NEXT: AtomicU64 = AtomicU64::new(0);
        let root = std::env::temp_dir().join(format!(
            "grund-1499-query-{}-{}",
            std::process::id(),
            NEXT.fetch_add(1, Ordering::Relaxed)
        ));
        fs::create_dir(&root).unwrap();
        let fixture = Self(root);
        let source = Path::new(env!("CARGO_MANIFEST_DIR"))
            .join("../../tests/e2e/support/member_query_guidance/repo");
        for file in [
            "grund.toml",
            "docs/da/README.md",
            "docs/da/DA-000-root.md",
            "worldsim/grund.toml",
            "worldsim/docs/da/README.md",
            "worldsim/docs/da/DA-010-worldsim.md",
            "tractor1/grund.toml",
            "tractor1/docs/da/README.md",
            "tractor1/docs/da/DA-001-tier1-purpose-built-vehicle.md",
        ] {
            let target = fixture.0.join(file);
            fs::create_dir_all(target.parent().unwrap()).unwrap();
            fs::copy(source.join(file), target).unwrap();
        }
        fixture
    }

    fn member(&self) -> PathBuf {
        self.0.join("worldsim")
    }

    fn root_success(&self) {
        let output = run(&self.0, &[ID, "--brief"]);
        assert_eq!(output.status.code(), Some(0), "{output:?}");
        assert!(String::from_utf8_lossy(&output.stdout).contains("The vehicle."));
        assert!(output.stderr.is_empty(), "{output:?}");
        let check = run(&self.0, &["check"]);
        let findings = format!(
            "{}{}",
            String::from_utf8_lossy(&check.stdout),
            String::from_utf8_lossy(&check.stderr)
        );
        assert!(!findings.contains("unknown project alias"), "{findings}");
    }
}

impl Drop for Workspace {
    fn drop(&mut self) {
        fs::remove_dir_all(&self.0).unwrap();
    }
}

fn run(cwd: &Path, args: &[&str]) -> Output {
    Command::new(env!("CARGO_BIN_EXE_grund"))
        .current_dir(cwd)
        .args(args)
        .env("NO_COLOR", "1")
        .output()
        .expect("run grund")
}

fn refusal(output: Output) -> String {
    assert_eq!(output.status.code(), Some(2), "{output:?}");
    assert!(output.stdout.is_empty(), "{output:?}");
    String::from_utf8(output.stderr).unwrap()
}

/// The intake script required an absolute root string. Accept the command-path
/// convention too, but prove the printed location reaches the actual root.
fn guidance(message: &str, cwd: &Path, root: &Path, alias: &str) -> PathBuf {
    assert!(
        message.starts_with(&format!("unknown project alias `{alias}`\n")),
        "{message}"
    );
    let note = message.lines().skip(1).collect::<Vec<_>>().join(" ");
    for meaning in ["workspace", "member", "root", alias] {
        assert!(
            note.contains(meaning),
            "missing {meaning:?} in enclosing-workspace guidance:\n{message}"
        );
    }
    assert!(
        note.contains("run") || note.contains("retry"),
        "missing root retry remedy:\n{message}"
    );
    assert!(
        note.contains("lookup") || note.contains("query") || note.contains("grund"),
        "missing query retry remedy:\n{message}"
    );
    let actual = root.canonicalize().unwrap();
    let location = note.split_whitespace().find_map(|word| {
        let word = word.trim_matches(['`', '\'', '"', ',', ';', ':', '(', ')']);
        let path = cwd.join(word);
        (path.canonicalize().ok().as_ref() == Some(&actual)).then_some(path)
    });
    location.unwrap_or_else(|| panic!("missing usable workspace root from {cwd:?}:\n{message}"))
}

fn show_retry(tree: &Workspace, cwd: &Path, args: &[&str]) {
    let stderr = refusal(run(cwd, args));
    let message = stderr.strip_prefix("error: ").expect("keep error prefix");
    let root = guidance(message, cwd, &tree.0, "tractor1");
    // Retry against the printed root, discarding an explicit member selector.
    // Merely running the original command after cd would keep selecting the member.
    let retry = run(cwd, &[ID, root.to_str().unwrap(), "--brief"]);
    assert_eq!(retry.status.code(), Some(0), "{retry:?}");
    assert!(String::from_utf8_lossy(&retry.stdout).contains("The vehicle."));
    assert!(retry.stderr.is_empty(), "{retry:?}");
}

#[test]
fn configured_member_bare_and_explicit_show_offer_root_retry() {
    let tree = Workspace::new();
    tree.root_success();
    for args in [
        vec![ID, "--brief"],
        vec!["show", ID, "--brief"],
        vec!["show", ID, "--format=json"],
    ] {
        show_retry(&tree, &tree.member(), &args);
    }
}

#[test]
fn explicit_member_path_and_nested_cwd_offer_invocation_relative_retry() {
    let tree = Workspace::new();
    let nested = tree.member().join("docs/da");
    show_retry(&tree, &nested, &[ID, "--brief"]);
    show_retry(&tree, &tree.0, &["show", ID, "worldsim", "--brief"]);
    show_retry(&tree, &tree.member(), &[ID, ".", "--brief"]);
}

#[test]
fn configless_member_offers_the_same_verified_retry() {
    let tree = Workspace::new();
    fs::remove_file(tree.member().join("grund.toml")).unwrap();
    tree.root_success();
    show_retry(&tree, &tree.member(), &[ID, "--brief"]);
    show_retry(&tree, &tree.0, &["show", ID, "worldsim", "--brief"]);
}

#[test]
fn verified_alias_guidance_does_not_scan_or_promise_target_existence() {
    let tree = Workspace::new();
    fs::write(tree.0.join("tractor1/docs/da/unreadable.md"), [0xff]).unwrap();
    for id in [ID, "tractor1/DA-missing", &format!("{ID}.999")] {
        let stderr = refusal(run(&tree.member(), &[id, "--brief"]));
        guidance(
            stderr.strip_prefix("error: ").unwrap(),
            &tree.member(),
            &tree.0,
            "tractor1",
        );
    }
}

#[test]
fn json_batch_show_preserves_unknown_project_record_with_guidance() {
    let tree = Workspace::new();
    let mut child = Command::new(env!("CARGO_BIN_EXE_grund"))
        .current_dir(tree.member())
        .args(["show", "--batch", "--format=json"])
        .stdin(Stdio::piped())
        .stdout(Stdio::piped())
        .stderr(Stdio::piped())
        .spawn()
        .unwrap();
    writeln!(child.stdin.take().unwrap(), "{}", json!({"id":ID})).unwrap();
    let output = child.wait_with_output().unwrap();
    assert_eq!(output.status.code(), Some(1), "{output:?}");
    assert!(output.stderr.is_empty(), "{output:?}");
    let record: Value = serde_json::from_slice(&output.stdout).unwrap();
    let finding = &record["error"];
    let message = finding["message"].as_str().unwrap();
    assert_eq!(
        *finding,
        json!({"severity":"error", "path":null, "line":null,
               "code":"unknown-project", "message":message,
               "sites":null, "authority":null})
    );
    assert_eq!(
        record,
        json!({"query":{"id":ID,"section":null},
        "ok":false,"result":null,"error":finding})
    );
    guidance(message, &tree.member(), &tree.0, "tractor1");
}

#[test]
fn refs_shares_verified_alias_refusal() {
    let tree = Workspace::new();
    let stderr = refusal(run(&tree.member(), &["refs", ID]));
    guidance(
        stderr.strip_prefix("error: ").unwrap(),
        &tree.member(),
        &tree.0,
        "tractor1",
    );
}

#[test]
fn fetch_shares_verified_alias_refusal() {
    let tree = Workspace::new();
    let stderr = refusal(run(&tree.member(), &["fetch", ID]));
    guidance(
        stderr.strip_prefix("error: ").unwrap(),
        &tree.member(),
        &tree.0,
        "tractor1",
    );
}

#[test]
fn unknown_alias_standalone_and_unlisted_keep_generic_fallback() {
    let tree = Workspace::new();
    let standalone = Workspace::new();
    fs::remove_file(standalone.0.join("grund.toml")).unwrap();
    let unlisted = tree.0.join("unlisted");
    fs::create_dir(&unlisted).unwrap();
    fs::copy(
        tree.member().join("grund.toml"),
        unlisted.join("grund.toml"),
    )
    .unwrap();
    for (cwd, id, alias) in [
        (tree.member(), "ghost/DA-missing", "ghost"),
        (standalone.member(), ID, "tractor1"),
        (unlisted, ID, "tractor1"),
    ] {
        for command in ["show", "refs", "fetch"] {
            assert_eq!(
                refusal(run(&cwd, &[command, id])),
                format!("error: unknown project alias `{alias}`\n{GENERIC}\n")
            );
        }
    }
}

#[test]
fn undecidable_enclosing_membership_keeps_generic_fallback() {
    let tree = Workspace::new();
    fs::write(
        tree.0.join("grund.toml"),
        "grund_config_version = 2\n[workspace]\nmembers = [\"worldsim\"\n",
    )
    .unwrap();
    assert_eq!(
        refusal(run(&tree.member(), &[ID, "--brief"])),
        format!("error: unknown project alias `tractor1`\n{GENERIC}\n")
    );
}
