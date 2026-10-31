#!/usr/bin/env python3
"""Derive complete native service experiments (§AR-ci.requirements.1.verification).

Only checkout, experimental cache identities/transport and publication conditions
change. Transaction validation is an explicitly separate non-sample condition.
"""

from copy import deepcopy
from pathlib import Path

import yaml

from node_cache_measure import BASE

CONFIG = "fromJSON(inputs.configuration)"
CONDITION = f"{CONFIG}.condition"
SOURCE = f"{CONFIG}.source"
TOOLS = "${{ runner.temp }}/grund-1122-tools"
WORK = "${{ runner.temp }}/grund-1122-measure"
SAMPLE = f"{CONDITION} != 'validate'"
SAVE = f"{CONDITION} == 'seed' || {CONDITION} == 'save'"


def expression(value):
    return "${{ " + value + " }}"


class WorkflowDumper(yaml.SafeDumper):
    """Keep generated shell commands reviewable (§AR-ci.requirements.1.verification)."""


def scalar(dumper, value):
    return dumper.represent_scalar("tag:yaml.org,2002:str", value,
                                   style="|" if "\n" in value else None)


WorkflowDumper.add_representer(str, scalar)


def service(command, name, **extra):
    # A JavaScript action receives the runner's cache-service runtime token.
    # Its Python/Node children inherit that environment; ordinary run steps do not.
    return {"name": name, "uses": "actions/github-script@v8", **extra, "with": {
        "script": "await exec.exec('python', [process.env.MEASURE_TOOLS + '/node_cache_measure.py', "
        + ", ".join(repr(x) for x in command.split())
        + "], {env: {...process.env, MEASURE_NODE: process.execPath}});"}}


def job(workflow, name):
    """Retain every production suite, proof and post action in measured jobs."""
    original = yaml.safe_load(Path(f".github/workflows/{workflow}").read_text())
    result = deepcopy(original["jobs"][name])
    result["env"] = {**original.get("env", {}), "MEASURE_WORKFLOW": workflow,
                     "MEASURE_JOB": name, "MEASURE_CONFIG": "${{ inputs.configuration }}",
                     "MEASURE_TOOLS": TOOLS, "GH_TOKEN": "${{ github.token }}",
                     "PYTHONDONTWRITEBYTECODE": "1"}
    result["if"] = expression(CONFIG + (".os != 'macOS'" if name == "node" else ".os == 'macOS'"))
    if name == "node":
        result["name"] = "node acceptance (${{ matrix.os }})"
        result["runs-on"] = "${{ matrix.os }}"
        result["strategy"] = {"fail-fast": False, "matrix": {"os": expression(CONFIG + ".node_systems")}}
    rewritten = [
        {"uses": "actions/checkout@v6"},
        {"name": "Preserve the independent pinned harness", "shell": "bash", "run":
         'python - <<\'PY\'\nimport os, pathlib, shutil\n'
         'out = pathlib.Path(os.environ["RUNNER_TEMP"]) / "grund-1122-tools"\n'
         'out.mkdir()\n'
         'for source in pathlib.Path("scripts").glob("node_cache_*.py"):\n'
         '    shutil.copy2(source, out / source.name)\n'
         'shutil.copy2("scripts/node_cache_measure_service.cjs", out)\n'
         'for source in pathlib.Path("scripts/node-cache-toolkit").iterdir():\n'
         '    if source.is_file(): shutil.copy2(source, out / source.name)\nPY\n'},
        {"uses": "actions/checkout@v6", "with": {"ref": expression(SOURCE), "fetch-depth": 0}},
    ]
    for original_step in result["steps"][1:]:
        step = deepcopy(original_step)
        if step.get("name") == "Restore cargo registry and target":
            rewritten.extend([
                {"name": "Install pinned experimental cache toolkit", "shell": "bash", "run":
                 f'python -m pip install PyYAML==6.0.2\nnpm ci --prefix "{TOOLS}" --ignore-scripts --no-audit --no-fund\n'},
                {"name": "Verify scope and plan every cache identity", "shell": "bash",
                 "run": f'python "{TOOLS}/node_cache_measure.py" initialize'},
                {"name": "Persist the pre-write intention ledger", "uses": "actions/upload-artifact@v4",
                 "with": {"name": "${{ runner.os }}-${{ github.run_attempt }}-ledger",
                          "path": WORK + "/evidence/ledger.json", "retention-days": 14,
                          "if-no-files-found": "error"}},
                {"name": "Download exact seed provenance (no archive artifacts)",
                 "if": expression(f"{CONDITION} != 'seed'"), "uses": "actions/download-artifact@v5",
                 "with": {"name": "${{ runner.os }}-${{ fromJSON(inputs.configuration).seed_attempt }}-evidence",
                          "path": WORK + "/seeds", "github-token": "${{ github.token }}",
                          "repository": "${{ github.repository }}", "run-id": expression(CONFIG + ".seed_run")}},
            ])
        uses = step.get("uses", "")
        if uses.startswith("actions/cache/"):
            operation = "restore" if "/restore@" in uses else "save"
            cache_id = step["id"] if operation == "restore" else next(
                s["id"] for s in result["steps"] if "id" in s
                and all(s.get("with", {}).get(k) == step["with"][k] for k in ("path", "key")))
            step = service(operation + " " + cache_id, step["name"])
            if operation == "restore":
                step["id"] = cache_id
            else:
                step["if"] = expression(SAVE)
                if cache_id == "node-target":
                    step["if"] = expression(f"({SAVE}) && ({SOURCE} == '{BASE}' || steps.node-publication.outputs.ready == 'true')")
        elif step.get("name") == "Materialize Node dependencies":
            step["if"] = expression(f"{SAMPLE} && {SOURCE} != '{BASE}' && steps.node-target.outputs.cache-matched-key != ''")
        elif step.get("name") == "Prepare Node dependency publication":
            step["if"] = expression(f"({SAVE}) && {SOURCE} != '{BASE}'")
        elif "if" in step:
            step["if"] = expression(SAVE)  # Production ordinary-Cargo pruning.
        elif any(s.get("name") == "Restore cargo registry and target" for s in rewritten):
            step["if"] = expression(SAMPLE)
        rewritten.append(step)
    rewritten.extend([
        service("validate", "Validate repeated native cache-service round trips",
                **{"if": expression(f"{CONDITION} == 'validate'")}),
        {"name": "Require complete Node publication in save samples", "shell": "bash",
         "if": expression(f"({SAVE}) && {SOURCE} != '{BASE}'"),
         "run": '[ "${{ steps.node-publication.outputs.ready }}" = true ]'},
        {"name": "Retain all transaction and gate evidence before cleanup", "if": "always()",
         "uses": "actions/upload-artifact@v4", "with": {
             "name": "${{ runner.os }}-${{ github.run_attempt }}-evidence", "path": WORK + "/evidence",
             "retention-days": 14, "if-no-files-found": "error"}},
        {"name": "Delete exactly this batch (retain only successful seeds)",
         "if": expression(f"always() && ({CONDITION} != 'seed' || failure() || cancelled())"),
         "shell": "bash", "run": f'python "{TOOLS}/node_cache_measure.py" cleanup-local'},
        {"name": "Retain cleanup identities and absence checks", "if": "always()",
         "uses": "actions/upload-artifact@v4", "with": {
             "name": "${{ runner.os }}-${{ github.run_attempt }}-cleanup", "path": WORK + "/evidence",
             "retention-days": 14, "if-no-files-found": "error"}},
    ])
    result["steps"] = rewritten
    return result


def main():
    configuration = {"description": "Explicit mode, pinned pair/harness, OS, seed_run/attempt, condition and label JSON",
                     "required": True, "type": "string"}
    document = {"name": "Node cache native measurement", "on": {"workflow_call": {"inputs": {
        "configuration": configuration}}}, "permissions": {"contents": "read", "actions": "write"},
        "concurrency": {"group": "grund-1122-experiment", "cancel-in-progress": False},
        "jobs": {"node": job("ci-leg.yml", "node"), "macos": job("macos-suites.yml", "macos")}}
    Path(".github/workflows/node-cache-measure.yml").write_text(
        "# §AR-ci.requirements.1.verification: isolated service experiment; generated by\n"
        "# scripts/node_cache_measure_workflow.py from complete production jobs.\n"
        + yaml.dump(document, Dumper=WorkflowDumper, sort_keys=False, width=1000, allow_unicode=True),
        encoding="utf-8")


if __name__ == "__main__":
    main()
