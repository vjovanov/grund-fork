//! Complete Node Rust peers with the host's invocation CWD
//! (§REQ-one-answer.proof.matrix, §FS-workspace.8.1.3).

use grund_core::{node_embedding_call, node_request};
use serde_json::{Value, json};
use std::io::{BufRead, BufReader, Write};
use std::path::Path;
use std::process::{Child, ChildStdin, ChildStdout, Command, Stdio};

const PREFIX: &str = "GRUND-NODE-PEER ";

pub struct Worker {
    child: Child,
    input: Option<ChildStdin>,
    output: BufReader<ChildStdout>,
}

impl Worker {
    pub fn new() -> Self {
        let mut child = Command::new(std::env::current_exe().expect("test executable"))
            .args(["--exact", "agreement_node_worker::serve", "--nocapture"])
            .env("GRUND_AGREEMENT_NODE_WORKER", "1")
            .current_dir(super::agreement_host::repository())
            .stdin(Stdio::piped())
            .stdout(Stdio::piped())
            .stderr(Stdio::inherit())
            .spawn()
            .expect("isolated Node Rust peer");
        let input = child.stdin.take();
        let output = BufReader::new(child.stdout.take().unwrap());
        let mut worker = Self {
            child,
            input,
            output,
        };
        assert_eq!(worker.read(), json!({"ready":true}));
        worker
    }

    fn read(&mut self) -> Value {
        loop {
            let mut line = String::new();
            assert!(
                self.output
                    .read_line(&mut line)
                    .expect("Node Rust response")
                    > 0,
                "Node Rust worker terminated: {:?}",
                self.child.try_wait()
            );
            if let Some((_, response)) = line.split_once(PREFIX) {
                return serde_json::from_str(response).expect("structured Node Rust response");
            }
        }
    }

    pub fn call(&mut self, request: Value) -> Value {
        let input = self.input.as_mut().expect("live Node Rust worker");
        serde_json::to_writer(&mut *input, &request).unwrap();
        writeln!(input).unwrap();
        input.flush().unwrap();
        let response = self.read();
        assert_eq!(response["request"], request, "peer answered another call");
        assert_eq!(
            Path::new(response["cwd"].as_str().unwrap())
                .canonicalize()
                .unwrap(),
            Path::new(request["cwd"].as_str().unwrap())
                .canonicalize()
                .unwrap(),
            "peer used another invocation CWD"
        );
        response["envelope"].clone()
    }
}

impl Drop for Worker {
    fn drop(&mut self) {
        drop(self.input.take());
        if std::thread::panicking() {
            let _ = self.child.kill();
        }
        assert!(
            self.child.wait().expect("Node Rust worker exit").success() || std::thread::panicking()
        );
    }
}

/// Only the selected child test serves requests. Its CWD cannot race the parent
/// suite; each reply keeps the complete, unmodified embedding envelope.
#[test]
fn serve() {
    if std::env::var_os("GRUND_AGREEMENT_NODE_WORKER").is_none() {
        return;
    }
    let send = |value: Value| {
        println!("{PREFIX}{value}");
        std::io::stdout().flush().unwrap();
    };
    send(json!({"ready":true}));
    for line in std::io::stdin().lock().lines() {
        let request: Value = serde_json::from_str(&line.unwrap()).unwrap();
        let cwd = Path::new(request["cwd"].as_str().unwrap());
        std::env::set_current_dir(cwd).unwrap();
        let actual_cwd = std::env::current_dir().unwrap();
        let envelope = node_embedding_call(node_request(
            request["operation"].as_str().unwrap(),
            request["args"].as_array().unwrap().clone(),
            cwd,
        ));
        // Release fixture directories before the parent removes their trees,
        // including on Windows where a process CWD can prevent removal.
        std::env::set_current_dir(super::agreement_host::repository()).unwrap();
        send(json!({"request":request,"cwd":actual_cwd,"envelope":envelope}));
    }
}

/// §FS-workspace.8.1.3: changing an absolute input root does not set invocation
/// CWD. Repeated peer calls must use each requested CWD and leave the parent alone.
#[test]
fn peer_preserves_invocation_relative_workspace_retry() {
    use super::agreement_tree::{CONFIG_SLUG, Tree};

    let root_config = format!("{CONFIG_SLUG}\n[workspace]\nmembers = [\"member\"]\n");
    let member_config = CONFIG_SLUG.replace("project_name = \"t\"", "project_name = \"member\"");
    let tree = Tree::new(
        "grund-1499-node-peer",
        &[
            ("grund.toml", &root_config),
            ("member/grund.toml", &member_config),
            (
                "member/docs/deep/keep.md",
                "Authored nested invocation directory.\n",
            ),
        ],
    );
    let parent_cwd = std::env::current_dir().unwrap();
    let mut worker = Worker::new();
    for (relative, location) in [
        ("member", ".."),
        ("member/docs/deep", "../../.."),
        ("", "."),
    ] {
        let cwd = tree.0.join(relative);
        let answer = worker.call(json!({"operation":"show","cwd":cwd,
            "args":["member/FS-absent",{"root":tree.0.join("member")}]}));
        let message = answer["failure"]["message"].as_str().unwrap();
        let prefix = "unknown project alias `member`\nnote: alias `member` belongs to the enclosing workspace at ";
        let (printed, retry) = message.strip_prefix(prefix).unwrap().split_once(
            "; this run is member-local — retry the lookup against the workspace root, replacing any explicit member <path> with "
        ).unwrap();
        assert_eq!(printed, location);
        assert_eq!(retry, printed);
        for word in [printed, retry] {
            assert_eq!(
                cwd.join(word).canonicalize().unwrap(),
                tree.0.canonicalize().unwrap()
            );
        }
        assert_eq!(answer["failure"]["code"], "unknown-project");
        assert!(answer["result"].is_null());
        assert_eq!(std::env::current_dir().unwrap(), parent_cwd);
    }
}
