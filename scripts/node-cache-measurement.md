# Native measurement handoff for #1122

This harness exercises the complete Ubuntu and Windows Node jobs and the complete
macOS suites job for [§AR-ci.requirements.1.verification](../docs/architecture/AR-ci.md#requirements1verification-a-cost-correction-measures-comparable-full-gates).
Fix prepares it; review executes and assesses it after the lifecycle publishes
the branch. **R1-03 remains deferred: this artifact-only harness is not ready for
performance acceptance.** Apply the stopping rule below before spending samples.

The base source is `d338c4814a095fef54708e83367597c4e7955aad`; the candidate source is
`ca9c56079c5b70d4099757edcc10b8ea641e8b09`. The harness revision is the separate
commit containing this document and `.github/workflows/node-cache-measure.yml`,
recorded exactly in the fix-1 result. Do not substitute the moving branch
head for either source. A meaningful production correction requires new candidate
samples. Changing the harness requires new seeds and matched measurements too.

## Representation and limits

The candidate implements [§AR-ci.3.4.1.5](../docs/architecture/AR-ci.md#3415-a-dependency-only-publication-view-with-the-live-root-intact)
using `grund-node-target-dependencies`, a sibling snapshot of the live root,
and `node-target-v4-1.95.0` keys/prefixes. Both production workflow sites use
`scripts/node_cache_publication.py`. Each recorded owner's workspace metadata and
lock identify third-party package names. Their Cargo fingerprint directories
identify the unit hashes of reusable compiler artifacts and build-script state.
Only those files/directories and ownership/cache metadata enter the snapshot,
across dev/release, host/cross and nested targets. No Cargo clean is invoked and
an ownership-created target does not need a cache-directory tag. Old workspace
target names are excluded by the same positive selection as current names.
Bundled Node sources are a subset of the owning workspace members. Third-party
packages are retained regardless of their names (including `grund-vendor`).
The separate tools tree is omitted. No local target selector or reclaimer changes.

Restore copies snapshot files back to the same checkout-relative paths without
overwriting existing live files. A failed cache restore does not materialize its
partial archive. Preparation failure warns, removes its snapshot, emits no ready
output and suppresses publication. Unreadable/missing owners, unknown layouts or
symlinks fail closed; they do not authorize deleting live output or publishing an
unfiltered target. Restore/save keep their existing events and main-only Node-miss
guards; ordinary Cargo cache hits cannot suppress Node preparation. Version 3
entries are not restore fallbacks. Production Cargo/Python caches are unchanged.

The experiment changes cache transport, explicitly. It uses `@actions/cache@5.1.0`
(the library locked by `actions/cache@v5` when inspected on 2026-10-31), including
its actual glob resolution, platform tar selection and compression options.
Archives use the source workflow's selected paths. The native tar commands are
visible in logs. Artifacts, with artifact compression disabled, carry the already
compressed archives; production cache APIs are never invoked. New Node source
proof and publication regressions count in the candidate gate.

**Uncalibrated artifact transport is not cache-service transport.** The harness
does not manufacture a full-gate performance verdict. Review must quantify the
download/upload/finalization difference against comparable native cache-service
measurements, including uncertainty, or report performance acceptance inconclusive.
The missing capability is a measured cache-service transport calibration for the
same archive sizes/native environments; smaller archives or artifact-only means
cannot discharge it. Existing historical logs can inform calibration but are not
the paired full-job baseline. No permission to publish branch production caches
or change event policy is implied.

## R1-03 stopping rule and concrete unblock

Review-1 established the registered route in fork run `41204365529`; cancellation
left zero valid samples, not a failed dispatch or an access denial. Do not reuse
that run as a seed. Its Windows historical upload tails exclude the initial
transfer interval, restore and part of finalization, and cover neither Ubuntu
nor macOS. No finite three-OS upload/restore/finalization bound follows from them.

The present permission boundary allows artifact publication and explicitly
forbids branch cache publication. Neither this harness nor read-only GitHub APIs
can time cache creation, signed upload and finalization of these exact archives
without writing an entry. Artifact timing or an unrelated production step's
maximum is not an evidence-backed upper bound for that missing transaction.
No quantified calibration machinery is supplied or claimed in this fix round.

Stop before repeated exact/save samples until the supervisor supplies one of:

- Authorization and a separate scoped harness for temporary, experiment-only
  fork cache entries, isolated from every production key/prefix. That experiment
  must compare both services on identical archive bytes/sizes on all three OSes,
  time full restore/upload/finalization (including first byte and service setup),
  preserve raw logs and checksums, and remove only its experiment entries after
  measurement. The current harness never writes those entries.
- Native production instrumentation/evidence that already measures those full
  transactions for matched archives/environments on all three systems, with a
  defensible uncertainty envelope. The Windows tail evidence is insufficient.

The reviewer must assess the calibration's repeated per-OS/operation deltas and
spread, environment/size coverage and uncertainty before accepting a correction.
Reject unmatched inputs or missing phases. If uncertainty consumes the candidate's
margin below 900 seconds, collect more calibration/samples or return inconclusive.
Retain the calibration inputs, analysis, uncertainty and decision alongside the
raw native evidence under `runtime/review-2/calibration/`. Until that exists,
the commands below are conditional preparation, not an acceptance-ready route.

## Registration and derivation

Read-only API inspection found `pre-release-checks.yml` registered and active in
`vjovanov/grund-fork` (workflow ID `377966149`) and present on its default `main`.
Its optional `node-cache-experiment` JSON input routes to the reusable measurement
workflow at the dispatch's own commit. Empty input preserves the ordinary checks;
experiment input skips those checks and is restricted to this fork. Thus the
new reusable file needs no standalone workflow-dispatch registration. No default
branch edit, new branch or repository setting change is required. The lifecycle
completion publisher must first put the committed harness on `fix/issue-1122`.
Review-1's cancelled seed established hosted routing. No successful seed or
performance sample exists. Fix-1 makes no dispatch and leaves publication to its
completion callback.

The generated workflow derives source steps from the production Node and macOS
jobs. Regenerate with `python3 scripts/node_cache_measure_workflow.py` using
PyYAML 6.0.2. Only checkout, cache transport and the isolated experiment's
publication conditions change. The baseline skips the two candidate snapshot
commands. The independent harness is copied to `RUNNER_TEMP` before the pinned
source replaces the checkout. All source checkouts use the same native workspace
path. No test/build command is removed; the macOS job retains all four Python
selections, Rust build, self-check, watch contract and four Rust shards.

## Dispatch and seed preparation

Run the following only from the published harness checkout, as review. It requires
authenticated `gh` with fork Actions dispatch/read access, native hosted runner
capacity, artifact storage and registry access for unchanged source prerequisites.
The fork's existing Actions/permissions inspection established those permissions,
but did not reserve capacity or establish a successful harness run.

```bash
base=d338c4814a095fef54708e83367597c4e7955aad
candidate=ca9c56079c5b70d4099757edcc10b8ea641e8b09
# This handoff's commit is the separate harness SHA; compare it with the literal
# SHA in the fix-1 result. The older workflow-file commit omits this handoff.
harness=$(git log -1 --format=%H -- scripts/node-cache-measurement.md)
gh api repos/vjovanov/grund-fork/git/ref/heads/fix/issue-1122 --jq .object.sha
```

The returned fork SHA must equal `$harness` and the fix-1 result's harness
SHA. Dispatch checks this equality before sending; jobs also reject a moved ref.
Use a fresh unique label prefix if repeating an experiment. This helper returns
the run ID and waits for success, without identifying an old run as a new one:

```bash
dispatch_one() {
  local label="$1" source="$2" condition="$3" seed="${4:-}"
  python3 scripts/node_cache_measure.py dispatch --harness "$harness" \
    --source "$source" --condition "$condition" --seed-run "$seed" --label "$label" || return
  local id=""
  for attempt in $(seq 1 30); do
    id=$(gh run list --repo vjovanov/grund-fork --workflow pre-release-checks.yml \
      --branch fix/issue-1122 --event workflow_dispatch --limit 100 \
      --json databaseId,displayTitle --jq ".[] | select(.displayTitle == \"Node cache 1122 $label\") | .databaseId")
    [ -z "$id" ] || break
    sleep 2
  done
  [ -n "$id" ] || return 1
  gh run watch "$id" --repo vjovanov/grund-fork --exit-status >&2 || return
  printf '%s\n' "$id"
}
seed_base=$(dispatch_one r2-base-seed "$base" seed) || exit 1
seed_candidate=$(dispatch_one r2-candidate-seed "$candidate" seed) || exit 1
```

Each seed run executes all three complete native gates cold, applies the source's
publication preparation, creates three archives (Cargo, Node and TypeScript) per
OS, and uploads them as `Linux-seeds`, `Windows-seeds`, `macOS-seeds`. Seeds are
preparation, not measured samples. Baseline Node seeds retain the whole root;
candidate Node seeds use the filtered snapshot. All other seed paths come from
each pinned source's production workflow. Cold setup/network costs are recorded;
do not mix them into the warm paired sample mean.

## Paired samples and evidence

Run two successful samples per side, condition and native gate, alternating sides:

```bash
evidence="$HOME/ag/tmp/grund-1122-native-evidence"
mkdir -p "$evidence"
for condition in exact save; do
  for sample in 1 2; do
    run_base=$(dispatch_one "r2-base-$condition-$sample" "$base" "$condition" "$seed_base") || exit 1
    python3 scripts/node_cache_measure.py collect "$run_base" --out "$evidence/$run_base" || exit 1
    run_candidate=$(dispatch_one "r2-candidate-$condition-$sample" "$candidate" "$condition" "$seed_candidate") || exit 1
    python3 scripts/node_cache_measure.py collect "$run_candidate" --out "$evidence/$run_candidate" || exit 1
  done
done
python3 scripts/node_cache_measure.py collect "$seed_base" --out "$evidence/$seed_base"
python3 scripts/node_cache_measure.py collect "$seed_candidate" --out "$evidence/$seed_candidate"
```

Eight measured dispatches produce 24 complete native gate samples. `exact` restores
the matched seed and skips preparation/archive/upload as production does. `save`
restores the same source-matched seed as a simulated prefix hit, executes all
production publication preparation, and creates/uploads replacement archives.
All three ordinary cache keys miss in that save condition; this includes ordinary
Cargo pruning/save cost as well as the independently missed Node key. Simulated
requested/matched keys and the original source key expressions are recorded;
these are controlled identities, not claims of production cache-server hits.

Per-OS evidence artifacts include source/harness/run/job identities, seed
provenance, runner image/architecture, native workspace path, Rust/binding
Rust/Python/Node/npm/tar/zstd versions, toolkit-lock hash, cache selections and
match conditions, compressed byte counts/checksums, every selected file's
size/checksum and restore/archive timestamps. Seed archives include their own
compression/path manifest and provenance. Jobs reject different source inputs,
images, tools, paths, toolkit locks or corrupted seed archives. Compare baseline
and candidate environments too; equality with each side's own seed is necessary
but insufficient. Preserve dependency provenance and manifests when comparing.

`collect` writes `run.json`, `jobs.json`, `artifacts.json`, `logs.zip` and downloaded
artifacts. `run.json.html_url` and each job's `html_url` give exact URLs.
`jobs.json` contains raw start/completion times for every job and step. Report
`completed_at - started_at` for each complete job, including setup, downloads,
materialization, rebuilds, preparation, compression, transfer, evidence collection
and all post actions. Do not subtract copying or move proof to a seed job. The
archive helper's manifests/checksum reading is extra instrumentation overhead;
identify it in the mechanism accounting, retaining the measured full-job time.

Inspect full native logs for all source/fallback/CLI proof and the dev/release
build timing lines. Failed/missing proof and mismatched environments are rejected
samples, never savings. Calculate mean/min/max/spread separately for each
gate/side/condition. Also report a representative combined mean, stating weights
(the historical sample was five exact hits and three prefix/save jobs, so 5/8
exact plus 3/8 save is a useful declared mix). Explain preparation/restore,
archive and transfer seconds added/removed separately. After credible transport
calibration, every affected candidate gate needs useful margin below fifteen
minutes; increase the sample count when variance obscures it. An ordinary PR CI
pass is separate evidence. The old rolling eight-main-push meter stays untouched.
