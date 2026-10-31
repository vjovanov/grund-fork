// §AR-ci.requirements.1.verification: actual production-toolkit transactions,
// with phase instrumentation and archive identity checks before extraction.
const fs = require('node:fs');
const path = require('node:path');
const crypto = require('node:crypto');
const {execFileSync} = require('node:child_process');

async function main() {
  const request = JSON.parse(fs.readFileSync(process.argv[2], 'utf8'));
  const config = JSON.parse(process.env.MEASURE_CONFIG);
  if (process.env.GITHUB_REPOSITORY !== 'vjovanov/grund-fork' ||
      process.env.GITHUB_REF !== 'refs/heads/fix/issue-1122' ||
      process.env.GITHUB_EVENT_NAME !== 'workflow_dispatch' ||
      config.experiment !== 'grund-1122' || process.env.GITHUB_SHA !== config.harness ||
      process.env.RUNNER_OS !== config.os ||
      !request.key.startsWith('grund-1122-experiment-') ||
      (request.expected_key && !request.expected_key.startsWith('grund-1122-experiment-'))) {
    throw Error('cache transaction outside explicit experiment scope');
  }
  const record = {request, phases: [], started_at: new Date().toISOString()};
  const started = performance.now();
  const persist = () => fs.writeFileSync(request.result, JSON.stringify(record, null, 2));
  async function phase(name, action) {
    const beginning = performance.now();
    const item = {name, started_at: new Date().toISOString()};
    record.phases.push(item);
    console.log(JSON.stringify({phase: item, key: request.key}));
    persist();
    try { return await action(); }
    finally {
      item.seconds = (performance.now() - beginning) / 1000;
      console.log(JSON.stringify({phase: item, key: request.key}));
      persist();
    }
  }
  async function archive(file) {
    return phase('archive checksum', async () => {
      const hash = crypto.createHash('sha256');
      for await (const chunk of fs.createReadStream(file)) hash.update(chunk);
      const identity = {bytes: fs.statSync(file).size, sha256: hash.digest('hex')};
      record.archive = identity;
      console.log(JSON.stringify({archive: identity, key: request.key}));
      if (request.expected_archive && (identity.bytes !== request.expected_archive.bytes ||
                                     identity.sha256 !== request.expected_archive.sha256)) {
        throw Error('restored archive differs from exact recorded seed bytes');
      }
      return identity;
    });
  }
  try {
    const cache = require('@actions/cache');
    const utils = require('@actions/cache/lib/internal/cacheUtils');
    const tar = require('@actions/cache/lib/internal/tar');
    const http = require('@actions/cache/lib/internal/cacheHttpClient');
    const twirp = require('@actions/cache/lib/internal/shared/cacheTwirpClient');
    const service = require('@actions/cache/lib/internal/config');
    record.toolkit = require('@actions/cache/package.json').version;
    record.node_runtime = process.version;
    record.service = service.getCacheServiceVersion();
    if (record.toolkit !== '5.1.0' || record.service !== 'v2' || !cache.isFeatureAvailable()) {
      throw Error('expected pinned native cache toolkit and available v2 cache service');
    }
    const create = tar.createTar;
    tar.createTar = async (...args) => {
      record.resolved_paths = args[1];
      record.compression = args[2];
      await phase('archive creation', () => create(...args));
      const identity = await archive(path.join(args[0], utils.getCacheFileName(args[2])));
      // No service write has happened yet. Check total repository occupancy,
      // with serialized experiment jobs and two GiB of headroom.
      execFileSync('python', [path.join(__dirname, 'node_cache_experiment_ledger.py'),
                            String(identity.bytes)], {stdio: 'inherit'});
    };
    const extract = tar.extractTar;
    tar.extractTar = async (...args) => {
      await archive(args[0]);
      return phase('archive extraction', () => extract(...args));
    };
    for (const method of ['downloadCache', 'saveCache']) {
      const original = http[method];
      http[method] = (...args) => phase(method === 'saveCache' ? 'complete upload' : 'complete download',
                                      () => original(...args));
    }
    const clientFactory = twirp.internalCacheTwirpClient;
    twirp.internalCacheTwirpClient = (...args) => {
      const client = clientFactory(...args);
      for (const method of ['CreateCacheEntry', 'FinalizeCacheEntryUpload', 'GetCacheEntryDownloadURL']) {
        const original = client[method].bind(client);
        client[method] = async input => phase(method, async () => {
          const response = await original(input);
          // Do not persist runtime credentials or signed service URLs.
          record.version = input.version;
          if (response.matchedKey) {
            record.matched_key = response.matchedKey;
            if (response.matchedKey !== request.expected_key) {
              throw Error('service matched an unrecorded key; refusing download/extraction');
            }
          }
          if (response.entryId) record.cache_id = response.entryId;
          return response;
        });
      }
      return client;
    };
    record.initial_setup_seconds = (performance.now() - started) / 1000;
    if (request.operation === 'save') {
      const id = await phase('complete save transaction', () => cache.saveCache(request.paths, request.key));
      if (!(id > 0) || !record.archive || !record.phases.some(p => p.name === 'FinalizeCacheEntryUpload')) {
        throw Error('cache save did not complete/finalize');
      }
      record.cache_id = id;
    } else {
      const matched = await phase('complete restore transaction', () => cache.restoreCache(
        request.paths, request.key, request.key === request.expected_key ? [] : [request.expected_key]));
      if (matched !== request.expected_key || !record.archive) throw Error('required exact experiment seed missing');
    }
    record.success = true;
  } finally {
    record.completed_at = new Date().toISOString();
    record.seconds = (performance.now() - started) / 1000;
    persist();
  }
}

main().catch(error => { console.error(error); process.exitCode = 1; });
