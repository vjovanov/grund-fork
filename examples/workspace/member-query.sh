#!/usr/bin/env bash
# Demonstrate §FS-workspace.8.1.3: a member-local query earns a verified root retry.
set -eu

fixture_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)/repo"
mkdir -p "$HOME/ag/tmp"
demo_dir="$(mktemp -d "$HOME/ag/tmp/grund-1499-member-query.XXXXXX")"
trap 'rm -rf -- "$demo_dir"' EXIT
cp -R "$fixture_dir" "$demo_dir/repo"
cd "$demo_dir/repo/packages/api"

refusal() {
    status=0
    grund web/FS-session "$@" --brief >"$demo_dir/stdout" 2>"$demo_dir/stderr" || status=$?
    [ "$status" -eq 2 ]
    [ ! -s "$demo_dir/stdout" ]
    grep -F 'unknown project alias `web`' "$demo_dir/stderr"
    grep -F 'this run is member-local' "$demo_dir/stderr"
    grep -F "enclosing workspace at $root_location;" "$demo_dir/stderr" >/dev/null
}

# The root is relative to the invocation CWD, not the selected member path.
root_location=../..
refusal
grund web/FS-session "$root_location" --brief

cd ../..
root_location=.
refusal packages/api
# Replace the explicit member selector rather than keeping it after changing CWD.
grund web/FS-session "$root_location" --brief
echo "both workspace-root retries: exit 0"
