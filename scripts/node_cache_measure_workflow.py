#!/usr/bin/env python3
"""Derive isolated complete native jobs from production (§AR-ci.requirements.1.verification).

Run from the harness checkout with PyYAML installed to regenerate the reusable
workflow. Source commands stay verbatim; only checkout/cache transport and the
explicit experimental publication conditions differ. Baseline lacks the two
snapshot commands, so those are candidate-only.
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


def expression(value):
    return "${{ " + value + " }}"


class WorkflowDumper(yaml.SafeDumper):
    """Keep generated shell commands reviewable (§AR-ci.requirements.1.verification)."""


def scalar(dumper, value):
    return dumper.represent_scalar("tag:yaml.org,2002:str", value,
                                   style="|" if "\n" in value else None)


WorkflowDumper.add_representer(str, scalar)


def job(workflow, name):
    """Retain all source gate steps, including all macOS selections/shards (§AR-ci.requirements.1.verification)."""
    original = yaml.safe_load(Path(f".github/workflows/{workflow}").read_text())
    result = deepcopy(original["jobs"][name])
    result["env"] = {**original.get("env", {}), "MEASURE_WORKFLOW": workflow,
                     "MEASURE_JOB": name, "MEASURE_CONFIG": "${{ inputs.configuration }}"}
    if name == "node":
        result["name"] = "node acceptance (${{ matrix.os }})"
        result["runs-on"] = "${{ matrix.os }}"
        result["strategy"] = {"fail-fast": False, "matrix": {"os": ["ubuntu-latest", "windows-latest"]}}
    bootstrap = [
        {"uses": "actions/checkout@v6"},
        {"name": "Preserve the independent harness", "shell": "bash", "run":
         'python - <<\'PY\'\nimport os, pathlib, shutil\n'
         'out = pathlib.Path(os.environ["RUNNER_TEMP"]) / "grund-1122-tools"\n'
         'out.mkdir()\n'
         'for name in ("node_cache_measure.py", "node_cache_measure_archive.cjs"):\n'
         '    shutil.copy2(pathlib.Path("scripts") / name, out / name)\nPY\n'},
        {"uses": "actions/checkout@v6", "with": {"ref": expression(SOURCE), "fetch-depth": 0}},
    ]
    rewritten = bootstrap
    for step in result["steps"][1:]:
        step = deepcopy(step)
        if step.get("name") == "Restore cargo registry and target":
            rewritten.extend([
                {"name": "Install isolated archive tools", "shell": "bash", "run":
                 f'python -m pip install PyYAML==6.0.2\n'
                 f'npm install --prefix "{TOOLS}" --ignore-scripts --no-audit --no-fund @actions/cache@5.1.0\n'},
                {"name": "Download matched isolated seeds", "if": expression(f"{CONDITION} != 'seed'"),
                 "uses": "actions/download-artifact@v5", "with": {
                     "name": "${{ runner.os }}-seeds", "path": WORK + "/seeds",
                     "github-token": "${{ github.token }}", "repository": "${{ github.repository }}",
                     "run-id": expression(CONFIG + ".seed_run")}},
            ])
        uses = step.get("uses", "")
        if uses.startswith("actions/cache/"):
            operation = "restore" if "/restore@" in uses else "save"
            # Saves pair to the restore id, independent of key expression spelling.
            if operation == "restore":
                cache_id = step["id"]
            else:
                cache_id = next(s["id"] for s in result["steps"] if "id" in s
                                and all(s.get("with", {}).get(k) == step["with"][k]
                                        for k in ("path", "key")))
            replacement = {"name": step["name"], "shell": "bash", "run":
                           f'python "{TOOLS}/node_cache_measure.py" {operation} {cache_id}'}
            if operation == "restore":
                replacement["id"] = cache_id
            else:
                replacement["if"] = expression(f"{CONDITION} != 'exact'")
                if cache_id == "node-target":
                    # Production preparation may warn and skip publication. A
                    # sample must instead fail, never silently reuse its old seed.
                    replacement["run"] = (
                        'if [ "' + expression(SOURCE) + '" != "' + BASE + '" ]; then\n'
                        '  [ "${{ steps.node-publication.outputs.ready }}" = true ] || exit 1\n'
                        'fi\n' + replacement["run"])
            step = replacement
        elif "if" in step:
            step["if"] = expression(f"{CONDITION} != 'exact'")
        if step.get("name") in ("Materialize Node dependencies", "Prepare Node dependency publication"):
            condition = f"{SOURCE} != '{BASE}'"
            if step["name"] == "Prepare Node dependency publication":
                condition += f" && {CONDITION} != 'exact'"
            step["if"] = expression(condition)
        rewritten.append(step)
    rewritten.extend([
        {"name": "Upload isolated seeds or save-path transfer", "if": expression(f"{CONDITION} != 'exact'"),
         "uses": "actions/upload-artifact@v4", "with": {
             "name": "${{ runner.os }}-seeds", "path": WORK + "/seeds", "compression-level": 0,
             "retention-days": 7, "if-no-files-found": "error"}},
        {"name": "Retain measurement evidence", "if": "always()", "uses": "actions/upload-artifact@v4",
         "with": {"name": "${{ runner.os }}-evidence", "path": WORK + "/evidence",
                  "retention-days": 7, "if-no-files-found": "error"}},
    ])
    result["steps"] = rewritten
    return result


def main():
    """Generate the called workflow; the existing dispatch is its registration (§AR-ci.requirements.1.verification)."""
    configuration = {"description": "Immutable source/harness, condition (seed/exact/save), seed_run and sample label JSON",
                     "required": True, "type": "string"}
    document = {"name": "Node cache native measurement", "on": {"workflow_call": {"inputs": {
        "configuration": configuration}}}, "permissions": {"contents": "read", "actions": "read"},
        "jobs": {"node": job("ci-leg.yml", "node"), "macos": job("macos-suites.yml", "macos")}}
    path = Path(".github/workflows/node-cache-measure.yml")
    path.write_text("# §AR-ci.requirements.1.verification: isolated experiment; generated by\n"
                    "# scripts/node_cache_measure_workflow.py from the complete production jobs.\n"
                    + yaml.dump(document, Dumper=WorkflowDumper, sort_keys=False,
                                width=1000, allow_unicode=True), encoding="utf-8")


if __name__ == "__main__":
    main()
