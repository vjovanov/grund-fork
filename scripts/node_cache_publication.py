#!/usr/bin/env python3
"""Dependency-only snapshots and non-overwriting restore (§AR-ci.3.4.1.5).

Select third-party package fingerprints and the compiler/build artifacts they
identify. Never infer workspace output from its current target names: persistent
targets also contain earlier names. Nothing in this module invokes Cargo clean
or changes a live target, tagged or otherwise.
"""

import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import tempfile
import tomllib


def cargo(checkout, *arguments):
    """Read package identities with locked inputs only (§AR-ci.3.4.1.5)."""
    result = subprocess.run(
        ["cargo", *map(str, arguments), "--locked", "--offline"], cwd=checkout,
        capture_output=True, text=True, check=True,
    )
    return result.stdout


def owner(target):
    """Require the recorded source identity before selecting packages (§AR-ci.3.4.1.5)."""
    checkout = Path(json.loads((target / "checkout.json").read_text(encoding="utf-8"))["checkout"])
    if (not checkout.is_absolute() or checkout.resolve() != checkout
            or hashlib.sha256(os.fsencode(checkout)).hexdigest()[:16] != target.name):
        raise ValueError(f"unrecognized checkout ownership: {target}")
    metadata = json.loads(cargo(checkout, "metadata", "--no-deps", "--format-version", "1"))
    members = set(metadata["workspace_members"])
    workspace = {p["name"] for p in metadata["packages"] if p["id"] in members}
    if not workspace:
        raise ValueError(f"no workspace packages: {checkout}")
    # Reading the lock avoids fetching manifests for unbuilt foreign-platform
    # dependencies merely to prepare an offline optimization.
    lock = tomllib.loads((checkout / "Cargo.lock").read_text(encoding="utf-8"))
    dependencies = {p["name"] for p in lock["package"]}
    return dependencies - workspace


def copy_dependencies(target, copied, dependencies):
    """Select package-owned state across host/cross/nested profiles (§AR-ci.3.4.1.5).

    Cargo names fingerprint directories <package>-<unit hash>. That same hash
    identifies deps artifacts and build-script directories, regardless of the
    crate's library name or platform suffix. Only metadata-known third parties
    enter the view; stale/renamed workspace output cannot enter by omission.
    """
    def copy(source):
        destination = copied / source.relative_to(target)
        destination.parent.mkdir(parents=True, exist_ok=True)
        if source.is_dir():
            shutil.copytree(source, destination, copy_function=shutil.copy2)
        else:
            shutil.copy2(source, destination)

    copy(target / "checkout.json")
    fingerprint_roots = sorted(target.rglob(".fingerprint"))
    profiles = {path.parent for path in fingerprint_roots}
    for path in target.rglob("*"):
        if (path.name in ("CACHEDIR.TAG", ".rustc_info.json") and path.is_file()
                and not any(profile in path.parents for profile in profiles)):
            copy(path)
    for fingerprints in fingerprint_roots:
        profile = fingerprints.parent
        if profile.name not in ("debug", "release"):
            raise ValueError(f"unknown Cargo profile: {profile}")
        hashes = set()
        for fingerprint in fingerprints.iterdir():
            match = re.fullmatch(r"(.+)-([0-9a-f]{16})", fingerprint.name)
            if not match:
                raise ValueError(f"unrecognized Cargo fingerprint: {fingerprint}")
            if match[1] in dependencies:
                hashes.add(match[2])
                copy(fingerprint)
                build = profile / "build" / fingerprint.name
                if build.is_dir():
                    copy(build)
        deps = profile / "deps"
        if deps.is_dir():
            for artifact in deps.iterdir():
                match = re.search(r"-([0-9a-f]{16})(?:\.|$)", artifact.name)
                if match and match[1] in hashes:
                    copy(artifact)


def prepare(root, snapshot):
    """Publish only a completely cleaned copy, preserving the live bytes (§AR-ci.3.4.1.5)."""
    # Retire the previous restored view before work: a failed preparation must
    # never leave an old or partially filtered view eligible for a new save.
    if snapshot.exists():
        shutil.rmtree(snapshot)
    snapshot.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix=snapshot.name + "-", dir=snapshot.parent) as temporary:
        staged = Path(temporary) / "view"
        staged.mkdir()
        for target in sorted(root.iterdir()):
            if target.name == "tools":
                continue
            if not target.is_dir() or target.is_symlink():
                raise ValueError(f"unrecognized Node target: {target}")
            dependencies = owner(target)
            if any(p.is_symlink() for p in target.rglob("*")):
                raise ValueError(f"symlink in Node target: {target}")
            copied = staged / target.name
            copy_dependencies(target, copied, dependencies)
        staged.rename(snapshot)
    if os.environ.get("GITHUB_OUTPUT"):
        with open(os.environ["GITHUB_OUTPUT"], "a", encoding="utf-8") as output:
            output.write("ready=true\n")


def restore(root, snapshot):
    """Materialize at the same relative paths; never overwrite live output (§AR-ci.3.4.1.5)."""
    if not snapshot.is_dir():
        return
    for source in snapshot.rglob("*"):
        if source.is_symlink():
            raise ValueError(f"symlink in Node snapshot: {source}")
        if not source.is_file():
            continue
        destination = root / source.relative_to(snapshot)
        # Refuse live symlink parents too; cached files cannot redirect writes.
        if any(p.is_symlink() for p in (root, *destination.parents)):
            raise ValueError(f"symlink in restore destination: {destination}")
        destination.parent.mkdir(parents=True, exist_ok=True)
        try:
            with destination.open("xb") as output, source.open("rb") as input_file:
                shutil.copyfileobj(input_file, output)
        except FileExistsError:
            continue
        shutil.copystat(source, destination)


def main():
    """A publication failure only warns; the workflow saves only ready views (§AR-ci.3.4.1.5)."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("operation", choices=("prepare", "restore"))
    arguments = parser.parse_args()
    root = Path(os.environ.get("GRUND_NODE_TARGET", "~/ag/tmp/grund-node-target")).expanduser()
    snapshot = root.with_name(root.name + "-dependencies")
    try:
        {"prepare": prepare, "restore": restore}[arguments.operation](root, snapshot)
    except (OSError, ValueError, KeyError, TypeError, subprocess.SubprocessError) as error:
        if arguments.operation == "prepare" and snapshot.exists():
            shutil.rmtree(snapshot, ignore_errors=True)
        print(f"::warning::Node cache {arguments.operation} skipped: {error}")


if __name__ == "__main__":
    main()
