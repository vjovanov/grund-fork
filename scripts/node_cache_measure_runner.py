"""Native full-gate and transaction preflight (§AR-ci.requirements.1.verification)."""

import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import time

from node_cache_experiment_ledger import CACHE_IDS, exact_entry, planned, reconcile, remove, scope, write


def run(argv, **options):
    return subprocess.run(list(map(str, argv)), check=True, **options)


def read(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def checksum(path):
    digest = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def environment():
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


def context():
    config = json.loads(os.environ["MEASURE_CONFIG"])
    scope(config)
    from node_cache_measure import BASE, CANDIDATE
    if (config["source"] not in (BASE, CANDIDATE)
            or config["condition"] not in ("seed", "validate", "exact", "save")):
        raise ValueError("source/condition outside pinned experiment pair")
    source = run(["git", "rev-parse", "HEAD"], capture_output=True, text=True).stdout.strip()
    if source != config["source"]:
        raise ValueError("source checkout differs from pinned SHA")
    work = Path(os.environ["RUNNER_TEMP"]) / "grund-1122-measure"
    return config, work, work / "evidence"


def initialize():
    config, work, evidence = context()
    ledger = planned(config, os.environ["GITHUB_RUN_ID"], os.environ["GITHUB_RUN_ATTEMPT"],
                     os.environ["RUNNER_OS"])
    write(evidence / "ledger.json", ledger)
    write(evidence / "environment.json", environment())
    write(evidence / "scope.json", {"config": config, "repository": os.environ["GITHUB_REPOSITORY"],
                                    "ref": os.environ["GITHUB_REF"], "job": os.environ["GITHUB_JOB"],
                                    "run_url": os.environ["GITHUB_SERVER_URL"] + "/" +
                                    os.environ["GITHUB_REPOSITORY"] + "/actions/runs/" + ledger["run"]})


def selection(cache_id):
    import yaml
    workflow = Path(".github/workflows") / os.environ["MEASURE_WORKFLOW"]
    job = yaml.safe_load(workflow.read_text())["jobs"][os.environ["MEASURE_JOB"]]
    return next(step["with"] for step in job["steps"] if step.get("id") == cache_id)


def manifest(paths):
    files = {}
    for path in paths:
        path = Path(path)
        for file in (path.rglob("*") if path.is_dir() else [path]):
            if file.is_file():
                files[str(file)] = {"bytes": file.stat().st_size, "sha256": checksum(file)}
    return files


def transaction(operation, cache_id, label=None, seed=None):
    """Use real service transport; fail samples on optional-cache failures."""
    started = time.time()
    config, work, evidence = context()
    selected = selection(cache_id)
    paths = [str(Path(p).expanduser()) for p in selected["path"].splitlines() if p.strip()]
    ledger = read(evidence / "ledger.json")
    local_environment = read(evidence / "environment.json")
    label = label or ("seed" if config["condition"] == "seed" else "save")
    output_name = f"{cache_id}-{operation}" if label in ("seed", "save") else f"{label}-{cache_id}-{operation}"
    entries = [e for e in ledger["entries"] if e["cache_id"] == cache_id and e["operation"] == label]
    key = entries[0]["key"] if entries else None
    record = {"config": config, "source": config["source"], "harness": config["harness"],
              "environment": local_environment, "selection": selected, "paths": paths,
              "run": ledger["run"], "attempt": ledger["attempt"], "ref": ledger["ref"],
              "cache_id": cache_id, "condition": config["condition"], "started_at": started}
    if operation == "restore" and config["condition"] == "seed":
        matched = ""
    else:
        if operation == "restore":
            seed = seed or read(work / "seeds" / f"{cache_id}-save.json")
            if (seed["source"] != config["source"] or seed["harness"] != config["harness"]
                    or seed["environment"] != local_environment or seed["selection"] != selected):
                raise ValueError("seed source, harness, native environment or representation differs")
            seed_plan = planned(seed["config"], seed["run"], seed["attempt"], config["os"])
            if seed["key"] not in [e["key"] for e in seed_plan["entries"] if e["cache_id"] == cache_id]:
                raise ValueError("seed key is outside its recorded experiment plan")
            if seed["run"] != ledger["run"] and (seed["run"] != config["seed_run"]
                                                    or seed["config"]["condition"] != "seed"):
                raise ValueError("seed provenance is not the explicitly requested seed run")
            remote = exact_entry(seed["key"], seed["remote"]["id"])
            if remote is None or remote["size_in_bytes"] != seed["archive"]["bytes"]:
                raise ValueError("exact recorded experiment seed unavailable or size differs")
            key = key if config["condition"] == "save" and label == "save" else seed["key"]
            record["seed"] = {"run": seed["run"], "key": seed["key"], "remote": remote}
        else:
            if not key:
                raise ValueError("unplanned service write")
            write(evidence / f"{output_name}-manifest.json", manifest(paths))
        request = {"operation": operation, "paths": paths, "key": key,
                   "result": str(evidence / f"{output_name}-service.json")}
        if operation == "restore":
            request.update(expected_key=seed["key"], expected_archive=seed["archive"])
        write(work / "request.json", request)
        run([os.environ["MEASURE_NODE"], Path(__file__).parent / "node_cache_measure_service.cjs",
             work / "request.json"])
        service = read(request["result"])
        if not service.get("success"):
            raise ValueError("incomplete service transaction")
        record.update(key=key, archive=service["archive"], service=service,
                      requested_key=key, matched_key=service.get("matched_key"))
        if operation == "save":
            ledger = reconcile(ledger, evidence / "ledger.json")
            for _ in range(6):
                record["remote"] = exact_entry(key, service["cache_id"])
                if record["remote"] is not None:
                    break
                time.sleep(2)
            if record["remote"] is None:
                raise ValueError("finalized cache absent from exact REST ledger")
            record["manifest"] = f"{output_name}-manifest.json"
            record["manifest_sha256"] = checksum(evidence / record["manifest"])
            matched = key
        else:
            seed_manifest = work / "seeds" / seed["manifest"]
            # Validation round trips refer to this run's own manifest.
            if seed["run"] == ledger["run"]:
                seed_manifest = evidence / seed["manifest"]
            if checksum(seed_manifest) != seed["manifest_sha256"]:
                raise ValueError("seed file manifest differs")
            if manifest(paths) != read(seed_manifest):
                raise ValueError("restored file bytes differ from the exact recorded seed")
            matched = service["matched_key"]
    record.update(completed_at=time.time(), elapsed_seconds=time.time() - started)
    write(evidence / f"{output_name}.json", record)
    if operation == "restore":
        with open(os.environ["GITHUB_OUTPUT"], "a", encoding="utf-8") as output:
            output.write("cache-hit=" + str(config["condition"] in ("exact", "validate")).lower() + "\n")
            output.write("cache-matched-key=" + matched + "\n")
            output.write("cache-primary-key=" + (key or "") + "\n")
    return record


def validate():
    """Three matched-byte save/clear/restore trials, cleaning each entry immediately."""
    config, work, evidence = context()
    if config["condition"] != "validate":
        raise ValueError("not a transaction-validation dispatch")
    for trial in range(3):
        for cache_id in CACHE_IDS:
            label = f"validate-{trial}"
            saved = transaction("save", cache_id, label)
            for path in saved["paths"]:
                path = Path(path)
                if path.is_dir():
                    shutil.rmtree(path)
                elif path.exists():
                    path.unlink()
            transaction("restore", cache_id, label, saved)
            entry = next(e for e in read(evidence / "ledger.json")["entries"] if e["key"] == saved["key"])
            remove(entry, evidence / f"{label}-{cache_id}-cleanup.json")


def cleanup_local():
    config, work, evidence = context()
    path = evidence / "ledger.json"
    if not path.exists():
        return  # Initialization failed before the pre-write ledger existed.
    ledger = reconcile(read(path), path)
    for entry in ledger["entries"]:
        remove(entry, evidence / (entry["operation"] + "-" + entry["cache_id"] + "-cleanup.json"))
