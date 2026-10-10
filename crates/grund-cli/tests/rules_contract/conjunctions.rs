//! §FS-rules.3.5.4: a sentence joining clauses with ` and ` is refused as a
//! conjunction on both rule surfaces, never as an unknown kind named after a
//! fragment of the sentence.

use super::support::{case_repo, run, scratch_from, text, write};

/// §FS-rules.3.5.4's exact table, plus the §FS-rules.3.5 row it generalizes,
/// whose bytes stay as released.
const ROWS: [(&str, &str); 7] = [
    (
        "Each FS must cite at least one FS and must not cite any FS.",
        "\"Each FS must cite at least one FS.\" and \"Each FS must not cite any FS.\"",
    ),
    (
        "Each FS must cite exactly one FS and must not cite any FS.",
        "\"Each FS must cite exactly one FS.\" and \"Each FS must not cite any FS.\"",
    ),
    (
        "Each FS must cite at least one FS and must cite at most one FS.",
        "\"Each FS must cite at least one FS.\" and \"Each FS must cite at most one FS.\"",
    ),
    (
        "Each FS must not cite any FS and must cite at least one FS.",
        "\"Each FS must not cite any FS.\" and \"Each FS must cite at least one FS.\"",
    ),
    (
        "The requirements chapter of each FS must cite at least one FS and should not cite any FS.",
        "\"The requirements chapter of each FS must cite at least one FS.\" and \
         \"The requirements chapter of each FS should not cite any FS.\"",
    ),
    (
        "Each FS must cite at least one FS and must not cite any FS and should cite at most 2 FS.",
        "\"Each FS must cite at least one FS.\", \"Each FS must not cite any FS.\", and \
         \"Each FS should cite at most 2 FS.\"",
    ),
    (
        "Each FS must cite at least one GOAL and must not cite any AR.",
        "\"Each FS must cite at least one GOAL.\" and \"Each FS must not cite any AR.\"",
    ),
];

fn reason(forms: &str) -> String {
    format!("conjunctions are not accepted; accepted forms: {forms}")
}

/// §FS-rules.3.5.4: `check --rule` in a repository whose one kind is `FS`.
#[test]
fn a_conjunction_is_refused_by_name_under_check_rule() {
    let root = case_repo("check-rule-conjunction-one-kind");
    let mut wrong = Vec::new();
    for (sentence, forms) in ROWS {
        let output = run(&root, &["check", ".", "--rule", sentence]);
        let expected = format!("error: {}\n", reason(forms));
        let (exit, stdout, stderr) = (
            output.status.code(),
            text(&output.stdout),
            text(&output.stderr),
        );
        if exit != Some(2) || !stdout.is_empty() || stderr != expected {
            wrong.push(format!(
                "{sentence}\n  exit {exit:?}, stdout {stdout:?}\n  stderr   {stderr:?}\n  expected {expected:?}"
            ));
        }
    }
    assert!(wrong.is_empty(), "wrong refusals:\n{}", wrong.join("\n"));
}

/// §FS-rules.3.5.4, §FS-rules.7.1: a configured rule declaration carrying the
/// same sentence gets the same reason in its `invalid-rule` finding.
#[test]
fn a_conjunction_is_refused_by_name_in_a_rule_declaration() {
    let mut wrong = Vec::new();
    for (index, (sentence, forms)) in ROWS.iter().enumerate() {
        let root = scratch_from(
            &case_repo("check-rules-conjunction-declaration"),
            "conjunction-declaration",
        );
        write(
            &root,
            "docs/rules/RULE-split.md",
            &format!("# RULE-split: {sentence}\n\nOne requirement per sentence.\n"),
        );
        let output = run(&root, &["check", ".", "--only", "invalid-rule"]);
        let expected = format!(
            "docs/rules/RULE-split.md:1: error: RULE-split is not a valid rule: {}\n",
            reason(forms)
        );
        let stdout = text(&output.stdout);
        if output.status.code() != Some(1) || stdout != expected {
            wrong.push(format!(
                "row {index}: {sentence}\n  stdout   {stdout:?}\n  expected {expected:?}"
            ));
        }
    }
    assert!(wrong.is_empty(), "wrong findings:\n{}", wrong.join("\n"));
}

/// §FS-rules.3.5.4: ` and ` that no modality follows is not a conjunction, so a
/// chapter named `and` is still a subject.
#[test]
fn and_without_a_modality_after_it_is_not_a_conjunction() {
    let root = case_repo("check-rule-conjunction-one-kind");
    let sentence = "The and chapter of each FS must cite at least one FS.";
    let output = run(&root, &["check", ".", "--rule", sentence]);
    assert_ne!(
        output.status.code(),
        Some(2),
        "accepted sentence was refused: {}",
        text(&output.stderr)
    );
}
