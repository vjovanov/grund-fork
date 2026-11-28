//! Config-only context for a member's unknown-alias refusal (§FS-workspace.5.1.1,
//! §FS-workspace.8.1.3).

use std::path::Path;

use super::expand::{enclosing_workspace_of, expand_workspace_projects};
use super::members::AncestorWorkspaces;
use super::scope::{RootMode, derive_alias};
use crate::config::{Config, Run, command_path, path_word};

/// §FS-workspace.5.1.1: verified root-project identity and a location usable
/// from the invocation CWD, independent of the report's path-base setting.
pub(crate) struct MemberRootGuidance {
    alias: String,
    location: String,
}

impl MemberRootGuidance {
    /// §FS-workspace.5.1.1: explain only the actual root alias; the command
    /// validates the citation without promising that its target resolves.
    pub(crate) fn message(&self, namespace: &str) -> Option<String> {
        (namespace == self.alias).then(|| {
            format!(
                "unknown project alias {namespace}; {namespace} names the enclosing workspace's root project, and this project is a member of that workspace — {}",
                crate::model::remedies::unknown_project_root(&self.location)
            )
        })
    }
}

/// §FS-workspace.5.1.1: reuse the canonical membership verifier and alias
/// derivation without expanding or scanning the enclosing project's declarations.
/// An undecidable claim withholds the hint rather than changing the check's verdict:
/// one named and not answered, and one above the root whose `members` text cannot
/// be obtained (§FS-workspace.6.1.7), which may list that root under another.
pub(crate) fn member_root_guidance(run: &Run) -> Option<MemberRootGuidance> {
    let root = verified_enclosing_workspace(run)?;
    if !root.workspace_include_root {
        return None;
    }
    let alias = derive_alias(&root, None, RootMode::Root).ok()?;
    let location = workspace_location(&root.root)?;
    Some(MemberRootGuidance { alias, location })
}

/// §FS-workspace.8.1.3: the enclosing workspace's verified project aliases and
/// a root location usable from the invocation CWD, with no declarations loaded.
pub(crate) struct MemberQueryGuidance {
    aliases: Vec<String>,
    location: String,
}

impl MemberQueryGuidance {
    /// §FS-workspace.8.1.3: verify only the alias, never the requested ID or section.
    pub(crate) fn note(&self, namespace: &str) -> Option<String> {
        self.aliases.iter().any(|alias| alias == namespace).then(|| {
            format!(
                "note: alias `{namespace}` belongs to the enclosing workspace at {}; this run is member-local — retry the lookup against the workspace root, replacing any explicit member <path> with {}",
                self.location, self.location
            )
        })
    }
}

/// §FS-workspace.8.1.3: derive the alias map through canonical config expansion,
/// without scanning sibling declarations or letting an undecidable tree fail the query.
pub(crate) fn member_query_guidance(run: &Run) -> Option<MemberQueryGuidance> {
    let mut root = verified_enclosing_workspace(run)?;
    let location = path_word(&workspace_location(&root.root)?, &['-']);
    let projects = expand_workspace_projects(&mut root, &run.root).ok()?;
    if !projects
        .iter()
        .any(|project| project.config.root == run.root)
    {
        return None;
    }
    Some(MemberQueryGuidance {
        aliases: projects.into_iter().map(|project| project.alias).collect(),
        location,
    })
}

/// §FS-workspace.5.1.1, §FS-workspace.8.1.3: both refusals require the same
/// verified membership chain; an undecidable ancestor withholds either hint.
fn verified_enclosing_workspace(run: &Run) -> Option<Config> {
    let mut ancestors = AncestorWorkspaces::quiet_for_run_at(&run.root);
    let mut child = run.root.clone();
    let mut enclosing = None;
    while let Some(parent) = enclosing_workspace_of(&child, &run.cli_base, &mut ancestors).ok()? {
        child = parent.root.clone();
        enclosing = Some(parent);
    }
    // §FS-workspace.5.1.1: the top of the chain is the root only when nothing above
    // it could still claim it.
    if ancestors.has_undecidable_ancestor(&child) {
        return None;
    }
    enclosing
}

/// §FS-workspace.5.1.1, §FS-workspace.8.1.3: remedies name the root from the
/// invocation CWD, independently of report path settings or an explicit member path.
fn workspace_location(root: &Path) -> Option<String> {
    // No working directory, no location usable from it, so no hint.
    let cwd = std::env::current_dir().ok()?;
    // §FS-workspace.5.1.1: the root named from where the caller stands, spelled as a pasted
    // command spells it (§FS-config-migrate.6.5.1 item 1), and `.` for that directory itself.
    let location = match command_path(Some(&cwd), root) {
        here if here.is_empty() => ".".to_owned(),
        location => location,
    };
    Some(location)
}
