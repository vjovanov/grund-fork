#!/usr/bin/env python3
"""Dependency-only snapshots and non-overwriting restore (§AR-ci.3.4.1.5).

Cargo, rather than filename prefixes, knows a package's renamed targets, tests,
examples and build scripts. Clean a private copy using each owner's workspace
metadata. The staged Node source closure contains a subset of those workspace
members, so their bundled-source output is cleaned by the same package selectors.
Nothing in this module cleans a live target.
"""

import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile


def cargo(checkout, *arguments):
    """Read/clean with locked inputs only (§AR-ci.3.4.1.5)."""
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
    packages = [p["name"] for p in metadata["packages"] if p["id"] in members]
    if not packages:
        raise ValueError(f"no workspace packages: {checkout}")
    return checkout, [arg for name in packages for arg in ("-p", name)]


def clean_copy(target, checkout, packages):
    """Clean every host/cross and nested Cargo profile in the copy (§AR-ci.3.4.1.5)."""
    roots = {target, *(p.parent for p in target.rglob("CACHEDIR.TAG"))}
    profiles = sorted({p.parent for p in target.rglob(".fingerprint")})
    for profile in profiles:
        if profile.name not in ("debug", "release"):
            raise ValueError(f"unknown Cargo profile: {profile}")
        # Cargo tags each target root, including nested builder targets. Cross
        # output adds a triple between that root and the profile directory.
        build_root = max((p for p in roots if p in profile.parents), key=lambda p: len(p.parts))
        relative = profile.relative_to(build_root).parts
        cross = []
        if len(relative) == 2:
            cross = ["--target", relative[0]]
        elif len(relative) != 1:
            raise ValueError(f"unrecognized Cargo target layout: {profile}")
        cargo(checkout, "clean", "--target-dir", build_root, "--profile",
              "dev" if profile.name == "debug" else "release", *cross, *packages)
    for incremental in target.rglob("incremental"):
        if incremental.is_dir():
            shutil.rmtree(incremental)


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
            checkout, packages = owner(target)
            if any(p.is_symlink() for p in target.rglob("*")):
                raise ValueError(f"symlink in Node target: {target}")
            copied = staged / target.name
            shutil.copytree(target, copied, copy_function=shutil.copy2)
            clean_copy(copied, checkout, packages)
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
