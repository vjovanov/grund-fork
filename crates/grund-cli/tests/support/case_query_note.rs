//! Conciseness accounting for the required invocation-relative root words in
//! verified member-query guidance (§FS-workspace.8.1.3). Goldens remain exact.

/// Only the two identical root words are variable path cost; the alias and all
/// surrounding prose still count toward the ordinary stderr limit.
pub(super) fn prose_len(line: &str) -> Option<usize> {
    let (alias, rest) = line
        .strip_prefix("note: alias `")?
        .split_once("` belongs to the enclosing workspace at ")?;
    let (location, retry) = rest.split_once(
        "; this run is member-local — retry the lookup against the workspace root, replacing any explicit member <path> with "
    )?;
    (!alias.is_empty() && !location.is_empty() && location == retry)
        .then_some(line.len() - location.len() - retry.len())
}

#[cfg(test)]
mod tests {
    use super::super::assert_stderr_is_concise;

    fn note(alias: &str, location: &str, retry: &str) -> String {
        format!(
            "note: alias `{alias}` belongs to the enclosing workspace at {location}; this run is member-local — retry the lookup against the workspace root, replacing any explicit member <path> with {retry}"
        )
    }

    #[test]
    fn required_matching_root_words_do_not_consume_the_prose_budget() {
        let location = format!("workspaces/{}/root", "long-path/".repeat(20));
        let note = note("beta", &location, &location);
        assert!(note.len() > 180);
        for json_case in [false, true] {
            assert_stderr_is_concise("member-query", json_case, false, &note);
        }
    }

    #[test]
    fn malformed_notes_prose_growth_and_other_lines_keep_the_cap() {
        let location = format!("workspaces/{}/root", "long-path/".repeat(20));
        let valid = note("beta", &location, &location);
        for wrong in [
            note("beta", &location, "another-root"),
            note("beta", "", &location),
            note("", &location, &location),
            note(&"long-alias".repeat(20), &location, &location),
            format!("{valid}; unrelated explanatory prose"),
            valid.replacen("note: alias", "note: project", 1),
            format!("{valid}\nerror: {}", "x".repeat(180)),
        ] {
            for json_case in [false, true] {
                assert!(
                    std::panic::catch_unwind(|| {
                        assert_stderr_is_concise("member-query", json_case, false, &wrong);
                    })
                    .is_err(),
                    "unexpectedly accepted {wrong:?}"
                );
            }
        }
    }
}
