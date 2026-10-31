// §AR-ci.requirements.1.verification: use the cache toolkit's native glob/tar implementation.
// No cache service API is called. Artifact transport is recorded separately.
const fs = require('node:fs');
const path = require('node:path');
const utils = require('@actions/cache/lib/internal/cacheUtils');
const tar = require('@actions/cache/lib/internal/tar');

async function main() {
  const [operation, directory, patternsFile] = process.argv.slice(2);
  fs.mkdirSync(directory, {recursive: true});
  const metadataFile = path.join(directory, 'archive.json');
  if (operation === 'save') {
    const compression = await utils.getCompressionMethod();
    const patterns = JSON.parse(fs.readFileSync(patternsFile, 'utf8'));
    const paths = await utils.resolvePaths(patterns);
    if (!paths.length) throw Error('no cache paths matched');
    await tar.createTar(directory, paths, compression);
    fs.writeFileSync(metadataFile, JSON.stringify({
      compression, paths, file: utils.getCacheFileName(compression),
      toolkit: require('@actions/cache/package.json').version,
    }, null, 2));
  } else if (operation === 'restore') {
    const metadata = JSON.parse(fs.readFileSync(metadataFile, 'utf8'));
    await tar.extractTar(path.join(directory, metadata.file), metadata.compression);
  } else {
    throw Error('unknown archive operation: ' + operation);
  }
}

main().catch(error => { console.error(error); process.exitCode = 1; });
