#!/usr/bin/env python3
"""Isolated native cache experiment and evidence collection (§AR-ci.requirements.1.verification).

Invoked by the measurement workflow from RUNNER_TEMP, independently of its fixed
source checkout. This never reads/writes the production cache service.
"""

import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import time


BASE = "d338c4814a095fef54708e83367597c4e7955aad"
REPOSITORY = "vjovanov/grund-fork"
REF = "fix/issue-1122"


def run(argv, **options):
    """Keep subprocess failures visible in the native job (§AR-ci.requirements.1.verification)."""
    return subprocess.run(list(map(str, argv)), check=True, **options)


def read_json(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def write_json(path, data):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")


def checksum(path):
    """Identify archives and each selected file without loading them whole (§AR-ci.requirements.1.verification)."""
    digest = hashlib.sha256()
    with Path(path).open("rb") as input_file:
        for chunk in iter(lambda: input_file.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def environment():
    """Reject mismatched seed runners/toolchains instead of measuring them (§AR-ci.requirements.1.verification)."""
    versions = {}
    for argv in (["rustc", "-vV"], ["rustc", "+1.95.0", "-vV"], ["cargo", "--version"],
                 ["python", "--version"], ["node", "--version"], ["npm", "--version"],
                 ["tar", "--version"], ["zstd", "--version"], ["gtar", "--version"]):
        try:
            if os.name == "nt" and argv[0] == "npm":
                cli = Path(shutil.which("npm")).parent / "node_modules/npm/bin/npm-cli.js"
                argv = ["node", str(cli), *argv[1:]]
            result = subprocess.run(argv, capture_output=True, text=True)
            versions[" ".join(argv)] = (result.stdout + result.stderr).strip()
        except FileNotFoundError:
            versions[" ".join(argv)] = "absent"
    return {"versions": versions, "workspace": str(Path.cwd()),
            "image": {k: os.environ.get(k) for k in
                      ("ImageOS", "ImageVersion", "RUNNER_OS", "RUNNER_ARCH")},
            "toolkit_lock": checksum(Path(__file__).parent / "package-lock.json")}


def selected_cache(cache_id):
    """Read the selected source's actual path/key declaration (§AR-ci.requirements.1.verification)."""
    import yaml
    workflow = Path(".github/workflows") / os.environ["MEASURE_WORKFLOW"]
    job = yaml.safe_load(workflow.read_text())["jobs"][os.environ["MEASURE_JOB"]]
    return next(step["with"] for step in job["steps"] if step.get("id") == cache_id)


def cache(operation, cache_id):
    """Restore/prepare matched seeds and retain raw archive provenance (§AR-ci.requirements.1.verification)."""
    started = time.time()
    config = json.loads(os.environ["MEASURE_CONFIG"])
    tools = Path(__file__).parent
    work = Path(os.environ["RUNNER_TEMP"]) / "grund-1122-measure"
    evidence = work / "evidence"
    seeds = work / "seeds"
    location = seeds / cache_id
    current_environment = environment()
    source = run(["git", "rev-parse", "HEAD"], capture_output=True, text=True).stdout.strip()
    if source != config["source"]:
        raise ValueError("source checkout is not the pinned SHA")
    if os.environ["GITHUB_SHA"] != config["harness"]:
        raise ValueError("dispatch ref has moved from the pinned harness SHA")
    selection = selected_cache(cache_id)
    record = {"source": source, "harness": os.environ["GITHUB_SHA"],
              "run": os.environ["GITHUB_RUN_ID"], "job": os.environ["GITHUB_JOB"],
              "config": config, "selection": selection, "environment": current_environment,
              "event": os.environ["GITHUB_EVENT_NAME"], "cache_service": "not used",
              "match": "exact" if config["condition"] == "exact" else "prefix/save"}
    seed_key = f"isolated-{source}-{cache_id}-seed"
    record.update(requested_key=seed_key if config["condition"] == "exact" else
                  seed_key + "-new-primary", matched_key=seed_key if config["condition"] != "seed" else None)
    if operation == "restore":
        if config["condition"] != "seed":
            provenance = read_json(location / "provenance.json")
            if (provenance["source"] != source or provenance["environment"] != current_environment
                    or provenance["harness"] != config["harness"]):
                raise ValueError("seed source, runner image, paths, toolchain or toolkit lock differs")
            if provenance["selection"] != selection:
                raise ValueError("seed cache representation differs")
            archive = read_json(location / "archive.json")
            if checksum(location / archive["file"]) != provenance["archive_sha256"]:
                raise ValueError("seed archive checksum differs")
            run(["node", tools / "node_cache_measure_archive.cjs", "restore", location])
            record["seed"] = provenance
        with open(os.environ["GITHUB_OUTPUT"], "a", encoding="utf-8") as output:
            output.write("cache-hit=" + str(config["condition"] == "exact").lower() + "\n")
    else:
        location.mkdir(parents=True, exist_ok=True)
        paths = [str(Path(line).expanduser()) for line in selection["path"].splitlines() if line.strip()]
        write_json(work / "paths.json", paths)
        run(["node", tools / "node_cache_measure_archive.cjs", "save", location, work / "paths.json"])
        archive = read_json(location / "archive.json")
        manifest = {}
        for selected in archive["paths"]:
            path = Path(selected)
            for file in (path.rglob("*") if path.is_dir() else [path]):
                if file.is_file():
                    manifest[str(file)] = {"bytes": file.stat().st_size, "sha256": checksum(file)}
        record.update(archive_sha256=checksum(location / archive["file"]),
                      archive_bytes=(location / archive["file"]).stat().st_size)
        write_json(evidence / f"{cache_id}-manifest.json", manifest)
        write_json(location / "provenance.json", record)
        write_json(evidence / f"{cache_id}-archive.json", archive)
    record.update(started_at=started, completed_at=time.time(), elapsed_seconds=time.time() - started)
    write_json(evidence / f"{cache_id}-{operation}.json", record)


def dispatch(arguments):
    """Use the fork's already registered manual workflow at its permitted ref (§AR-ci.requirements.1.verification)."""
    for sha in (arguments.source, arguments.harness):
        if len(sha) != 40 or any(c not in "0123456789abcdef" for c in sha):
            raise ValueError("source and harness must be immutable 40-character SHAs")
    current = run(["gh", "api", f"repos/{REPOSITORY}/git/ref/heads/{REF}"],
                  capture_output=True, text=True)
    if json.loads(current.stdout)["object"]["sha"] != arguments.harness:
        raise ValueError("permitted fork branch does not point at the pinned harness")
    if arguments.condition != "seed" and not arguments.seed_run:
        raise ValueError("a measured sample requires its source-matched seed run")
    config = {"source": arguments.source, "harness": arguments.harness, "condition": arguments.condition,
              "seed_run": arguments.seed_run, "label": arguments.label}
    payload = {"ref": REF, "inputs": {"node-cache-experiment": json.dumps(config)}}
    run(["gh", "api", f"repos/{REPOSITORY}/actions/workflows/pre-release-checks.yml/dispatches",
         "--method", "POST", "--input", "-"], input=json.dumps(payload), text=True)


def collect(arguments):
    """Keep forge job/step times, full logs and artifacts, without inventing a verdict (§AR-ci.requirements.1.verification)."""
    destination = Path(arguments.out)
    destination.mkdir(parents=True, exist_ok=True)
    prefix = f"repos/{REPOSITORY}/actions/runs/{arguments.run}"
    for endpoint, name in ((prefix, "run"), (prefix + "/jobs?per_page=100", "jobs"),
                           (prefix + "/artifacts?per_page=100", "artifacts")):
        result = run(["gh", "api", endpoint], capture_output=True, text=True)
        write_json(destination / f"{name}.json", json.loads(result.stdout))
    with (destination / "logs.zip").open("wb") as output:
        run(["gh", "api", prefix + "/logs"], stdout=output)
    run(["gh", "run", "download", arguments.run, "--repo", REPOSITORY,
         "--dir", destination / "artifacts"])


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    for operation in ("restore", "save"):
        commands.add_parser(operation).add_argument("cache_id")
    send = commands.add_parser("dispatch")
    send.add_argument("--source", required=True)
    send.add_argument("--harness", required=True)
    send.add_argument("--condition", choices=("seed", "exact", "save"), required=True)
    send.add_argument("--seed-run", default="")
    send.add_argument("--label", required=True)
    collect_parser = commands.add_parser("collect")
    collect_parser.add_argument("run")
    collect_parser.add_argument("--out", required=True)
    args = parser.parse_args()
    if args.command in ("restore", "save"):
        cache(args.command, args.cache_id)
    elif args.command == "dispatch":
        dispatch(args)
    else:
        collect(args)


if __name__ == "__main__":
    main()
