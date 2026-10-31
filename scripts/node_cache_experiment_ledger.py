"""Exact-entry scope, capacity and cancellation recovery (§AR-ci.requirements.1.verification)."""

import json
import os
from pathlib import Path
import re
import subprocess
import time
from urllib.parse import urlencode

REPOSITORY = "vjovanov/grund-fork"
REF = "refs/heads/fix/issue-1122"
PREFIX = "grund-1122-experiment-"
CACHE_IDS = ("cargo", "node-target", "node-typescript")
SYSTEMS = {"Linux": "ubuntu-latest", "Windows": "windows-latest", "macOS": "macos-latest"}


def api(endpoint, method="GET"):
    result = subprocess.run(["gh", "api", "--method", method,
                             f"repos/{REPOSITORY}/{endpoint}"],
                            capture_output=True, text=True, check=True)
    return json.loads(result.stdout) if result.stdout.strip() else None


def write(path, data):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")


def scope(config):
    """All three positive checks precede every runner service transaction."""
    if (os.environ.get("GITHUB_REPOSITORY") != REPOSITORY
            or os.environ.get("GITHUB_REF") != REF
            or os.environ.get("GITHUB_EVENT_NAME") != "workflow_dispatch"
            or config.get("experiment") != "grund-1122"
            or os.environ.get("GITHUB_SHA") != config.get("harness")):
        raise ValueError("experiment requires the authorized fork, existing ref, explicit mode and pinned harness")
    if os.environ.get("RUNNER_OS") != config["os"]:
        raise ValueError("native OS differs from requested experiment")


def planned(config, run, attempt, system):
    """Persist a complete deterministic intention ledger before any service write."""
    for value in (config["source"], config["harness"]):
        if not re.fullmatch("[0-9a-f]{40}", value):
            raise ValueError("immutable SHA required")
    if not str(run).isdigit() or not str(attempt).isdigit() or system not in SYSTEMS:
        raise ValueError("invalid run, attempt or native OS")
    prefix = f"{PREFIX}{run}-{attempt}-{system}-{config['source']}-"
    operations = (["seed"] if config["condition"] == "seed" else
                  [f"validate-{i}" for i in range(3)] if config["condition"] == "validate" else
                  ["save"] if config["condition"] == "save" else [])
    return {"repository": REPOSITORY, "ref": REF, "run": str(run), "attempt": str(attempt),
            "os": system, "config": config, "entries": [
                {"key": prefix + operation + "-" + cache_id + "-entry", "id": None,
                 "ref": REF, "operation": operation, "cache_id": cache_id}
                for operation in operations for cache_id in CACHE_IDS]}


def caches():
    """Read all pages, so an older retained entry cannot evade the capacity check."""
    result = []
    page = 1
    while True:
        batch = api(f"actions/caches?per_page=100&page={page}")["actions_caches"]
        result.extend(batch)
        if len(batch) < 100:
            return result
        page += 1


def capacity(archive_bytes):
    """Serialize dispatches; reserve headroom without evicting any unrelated cache."""
    entries = caches()
    experiment = [e for e in entries if e["key"].startswith(PREFIX)]
    if len(experiment) >= 9 or sum(e["size_in_bytes"] for e in entries) + archive_bytes > 8 * 1024**3:
        raise ValueError("experiment retention/capacity bound reached; collect and clean recorded batches first")


def exact_entry(key, expected_id=None):
    if not key.startswith(PREFIX):
        raise ValueError("refusing a non-experiment key")
    records = api("actions/caches?" + urlencode({"key": key, "ref": REF, "per_page": 100}))
    selected = [e for e in records["actions_caches"] if e["key"] == key and e["ref"] == REF]
    if len(selected) > 1:
        raise ValueError("ambiguous exact cache identity")
    if selected and expected_id is not None and str(selected[0]["id"]) != str(expected_id):
        raise ValueError("cache ID differs from recorded identity")
    return selected[0] if selected else None


def reconcile(ledger, path):
    """Recover IDs after an interrupted finalize/ledger write, by exact planned key."""
    expected = planned(ledger["config"], ledger["run"], ledger["attempt"], ledger["os"])
    if (ledger["repository"] != REPOSITORY or ledger["ref"] != REF
            or [e["key"] for e in ledger["entries"]] != [e["key"] for e in expected["entries"]]):
        raise ValueError("ledger is outside its immutable experiment plan")
    for entry in ledger["entries"]:
        found = exact_entry(entry["key"], entry.get("id"))
        if found:
            entry.update(id=found["id"], ref=found["ref"], remote=found)
    write(path, ledger)
    return ledger


def remove(entry, journal):
    """Write identities before deletion and verify absence, never delete by prefix."""
    found = exact_entry(entry["key"], entry.get("id"))
    if found:
        write(journal, {"before_delete": found, "planned": entry})
        api(f"actions/caches/{found['id']}", "DELETE")
    for _ in range(5):
        if exact_entry(entry["key"]) is None:
            write(journal, {"before_delete": found, "planned": entry, "verified_absent": True})
            return
        time.sleep(2)
    raise ValueError("experiment entry still exists after exact-ID deletion")


def recover(run, destination):
    """Independent local recovery after cancellation, including a lost runner."""
    record = api(f"actions/runs/{run}")
    if (record["repository"]["full_name"] != REPOSITORY
            or record["head_branch"] != REF.removeprefix("refs/heads/")
            or record["event"] != "workflow_dispatch" or record["status"] != "completed"
            or record["path"].split("@")[0] != ".github/workflows/pre-release-checks.yml"):
        raise ValueError("recovery requires a terminal authorized fork dispatch")
    destination = Path(destination)
    destination.mkdir(parents=True, exist_ok=True)
    write(destination / "run.json", record)
    write(destination / "jobs.json", api(f"actions/runs/{run}/jobs?per_page=100"))
    with (destination / "logs.zip").open("wb") as output:
        subprocess.run(["gh", "api", f"repos/{REPOSITORY}/actions/runs/{run}/logs"],
                       stdout=output, check=True)
    artifacts = api(f"actions/runs/{run}/artifacts?per_page=100")["artifacts"]
    for artifact in artifacts:
        if not artifact["name"].endswith("-ledger"):
            continue
        location = destination / artifact["name"]
        if not location.exists():
            subprocess.run(["gh", "run", "download", str(run), "--repo", REPOSITORY,
                            "--name", artifact["name"], "--dir", str(location)], check=True)
        ledger = json.loads((location / "ledger.json").read_text())
        if (ledger["run"] != str(run) or ledger["config"]["harness"] != record["head_sha"]
                or int(ledger["attempt"]) > record["run_attempt"]):
            raise ValueError("ledger provenance differs from dispatch")
        ledger = reconcile(ledger, location / "recovered.json")
        for entry in ledger["entries"]:
            remove(entry, location / (entry["operation"] + "-" + entry["cache_id"] + "-cleanup.json"))
    remaining = [e for e in caches() if e["key"].startswith(f"{PREFIX}{run}-")]
    write(destination / "remaining.json", remaining)
    if remaining:
        raise ValueError("run retains unaccounted entries; preserve evidence and investigate exact identities")


if __name__ == "__main__":
    import sys
    scope(json.loads(os.environ["MEASURE_CONFIG"]))
    capacity(int(sys.argv[1]))
