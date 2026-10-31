"""Report complete native jobs and conservative spread (§AR-ci.requirements.1.verification).

The envelope is an empirical screen, not a confidence interval. Independent
review still checks native logs, proof/suite counts and seed comparability.
"""

from collections import defaultdict
from datetime import datetime
import json
from pathlib import Path
import statistics

from node_cache_experiment_ledger import CACHE_IDS, SYSTEMS, write
from node_cache_measure import BASE, CANDIDATE


def read(path):
    return json.loads(path.read_text(encoding="utf-8"))


def stats(values):
    spread = max(values) - min(values)
    deviation = statistics.stdev(values) if len(values) > 1 else 0
    return {"n": len(values), "mean": statistics.mean(values), "min": min(values), "max": max(values),
            "stdev": deviation, "range": spread, "envelope": max(spread, 2 * deviation)}


def analyze(directory, output, preflight_os=None):
    groups = defaultdict(list)
    steps = defaultdict(list)
    transactions = defaultdict(list)
    environments = defaultdict(list)
    provenance = []
    harnesses = set()
    seen = set()
    for scope_path in Path(directory).glob("*/artifacts/*-evidence/scope.json"):
        evidence = scope_path.parent
        scope = read(scope_path)
        config = scope["config"]
        run_directory = evidence.parents[1]
        run = read(run_directory / "run.json")
        ledger = read(evidence / "ledger.json")
        identity = (run["id"], ledger["attempt"], ledger["os"])
        if identity in seen:
            raise ValueError("duplicate sample identity")
        seen.add(identity)
        if (run["conclusion"] != "success" or str(run["id"]) != ledger["run"]
                or run["head_sha"] != config["harness"] or scope["ref"] != ledger["ref"]
                or config["source"] not in (BASE, CANDIDATE)):
            raise ValueError("inconsistent or unsuccessful native sample provenance")
        os_name, source, condition = config["os"], config["source"], config["condition"]
        harnesses.add(config["harness"])
        if condition == "seed":
            continue
        environments[os_name].append(read(evidence / "environment.json"))
        for path in evidence.glob("*-service.json"):
            record = read(path)
            if not record.get("success"):
                raise ValueError("failed service transaction in accepted run")
        if condition == "validate":
            provenance.append({"run": scope["run_url"], "source": source,
                               "harness": config["harness"], "condition": condition})
            for cache_id in CACHE_IDS:
                for operation in ("restore", "save"):
                    records = [read(evidence / f"validate-{trial}-{cache_id}-{operation}.json")
                               for trial in range(3)]
                    transactions[(os_name, source, cache_id, operation)].extend(
                        record["elapsed_seconds"] for record in records)
            continue
        successful = [j for j in read(run_directory / "jobs.json")["jobs"]
                      if j["conclusion"] == "success" and ("node acceptance (" in j["name"]
                                                           or "suites (macos-latest)" in j["name"])]
        if len(successful) != 1:
            raise ValueError("expected exactly one complete native gate per dispatch")
        job = successful[0]
        elapsed = (datetime.fromisoformat(job["completed_at"].replace("Z", "+00:00"))
                   - datetime.fromisoformat(job["started_at"].replace("Z", "+00:00"))).total_seconds()
        groups[(os_name, source, condition)].append(elapsed)
        for step in job["steps"]:
            if not step.get("started_at") or not step.get("completed_at"):
                continue
            duration = (datetime.fromisoformat(step["completed_at"].replace("Z", "+00:00"))
                        - datetime.fromisoformat(step["started_at"].replace("Z", "+00:00"))).total_seconds()
            steps[(os_name, source, condition, step["name"])].append(duration)
        provenance.append({"run": scope["run_url"], "job": job["html_url"], "source": source,
                           "harness": config["harness"], "condition": condition, "seconds": elapsed})
    failures = []
    if len(harnesses) != 1:
        failures.append("exactly one immutable harness required")
    for os_name in ([preflight_os] if preflight_os else SYSTEMS):
        values = environments[os_name]
        if not values or any(e != values[0] for e in values):
            failures.append(f"{os_name}: environments missing or differ")
        for source in (BASE, CANDIDATE):
            for condition in (() if preflight_os else ("exact", "save")):
                if len(groups[(os_name, source, condition)]) < 2:
                    failures.append(f"{os_name}/{source}/{condition}: need two complete successful jobs")
            for cache_id in CACHE_IDS:
                for operation in ("restore", "save"):
                    if len(transactions[(os_name, source, cache_id, operation)]) < 3:
                        failures.append(f"{os_name}/{source}/{cache_id}/{operation}: missing preflight variability")
    measurements = {"/".join(k): stats(v) for k, v in groups.items() if v}
    variability = {"/".join(k): stats(v) for k, v in transactions.items() if v}
    margins = {}
    weighted = {}
    # Declared before sampling: five exact and three prefix/save observations
    # in the preserved eight-job historical window. Also show both conditions.
    for os_name in ([] if preflight_os else SYSTEMS):
        for source in (BASE, CANDIDATE):
            weighted[os_name + "/" + source] = sum(
                weight * measurements.get("/".join((os_name, source, condition)), {"mean": 0})["mean"]
                for condition, weight in (("exact", 5 / 8), ("save", 3 / 8)))
        weighted_upper = 0
        for condition, weight in (("exact", 5 / 8), ("save", 3 / 8)):
            key = "/".join((os_name, CANDIDATE, condition))
            if key not in measurements:
                continue
            summary = measurements[key]
            # Add observed transaction variability to observed full-job spread.
            transaction_spread = sum(variability.get("/".join((os_name, CANDIDATE, c, op)),
                                                     {"envelope": 0})["envelope"]
                                     for c in CACHE_IDS for op in
                                     (("restore", "save") if condition == "save" else ("restore",)))
            upper = summary["mean"] + summary["envelope"] + transaction_spread
            margins[os_name + "/" + condition] = 900 - upper
            weighted_upper += weight * upper
        margins[os_name + "/weighted"] = 900 - weighted_upper
        if margins[os_name + "/weighted"] < 30:
            failures.append(f"{os_name}: less than 30 seconds empirical weighted margin; collect more or report inconclusive")
    result = {"full_jobs": measurements, "steps": {"/".join(k): stats(v) for k, v in steps.items()},
              "transaction_variability": variability,
              "candidate_margin_seconds": margins, "weighted_means": weighted,
              "weighting": {"exact": 5 / 8, "save": 3 / 8},
              "envelope": "range or two sample standard deviations, whichever is larger; add transaction envelopes",
              "provenance": provenance, "failures": failures,
              "proof_review": "required: inspect raw logs and ordinary Cargo/TypeScript seed manifests for equivalence"}
    write(output, result)
    if failures:
        raise ValueError("incomplete or inconclusive experiment; see recorded analysis failures")
