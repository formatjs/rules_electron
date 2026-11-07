const assert = require('node:assert/strict');
const crypto = require('node:crypto');
const fs = require('node:fs');
const http = require('node:http');
const path = require('node:path');
const zlib = require('node:zlib');
const { app, net } = require('electron');
const semver = require('semver');
const { DebUpdater, MacUpdater, NsisUpdater } = require('electron-updater');
const { resolveFiles } = require('electron-updater/out/providers/Provider');
const { computeOperations, OperationKind } = require('electron-updater/out/differentialDownloader/downloadPlanBuilder');
const yaml = require('js-yaml');

// Checks real updater discovery and blockmap planning. Never installs the fixture.
module.exports = async function checkUpdater() {
  const config = yaml.load(fs.readFileSync(path.join(process.resourcesPath, 'app-update.yml'), 'utf8'));
  assert.equal(config.provider, 'generic');
  assert.equal(config.updaterCacheDirName, 'sample-desktop-updater');
  const directory = path.join(process.resourcesPath, 'update-smoke-feed');
  const requests = [];
  const server = http.createServer((request, response) => {
    const name = decodeURIComponent(new URL(request.url, 'http://localhost').pathname.slice(1));
    if (!fs.readdirSync(directory).includes(name)) {
      response.writeHead(404).end();
      return;
    }
    requests.push(name);
    response.end(fs.readFileSync(path.join(directory, name)));
  });
  await new Promise((resolve, reject) => {
    server.once('error', reject);
    server.listen(0, '127.0.0.1', resolve);
  });
  try {
    const base = new URL(`http://127.0.0.1:${server.address().port}/`);
    const Updater = process.platform === 'win32' ? NsisUpdater : process.platform === 'darwin' ? MacUpdater : DebUpdater;
    const updater = new Updater({ ...config, url: base.href });
    updater.logger = null;
    updater.autoDownload = false;
    updater.autoInstallOnAppQuit = false;
    const result = await updater.checkForUpdates();
    assert.equal(result.updateInfo.version, '2.0.0');
    assert.equal(result.isUpdateAvailable, semver.gt(result.updateInfo.version, app.getVersion()));
    assert.equal(result.downloadPromise ?? null, null);
    const channel = process.platform === 'darwin' ? 'latest-mac.yml' : process.platform === 'win32' ? 'latest.yml' : `latest-linux${process.arch === 'x64' ? '' : '-' + process.arch}.yml`;
    assert.ok(requests.includes(channel));
    const [file] = resolveFiles(result.updateInfo, base);
    const bytes = Buffer.from(await (await net.fetch(file.url.href)).arrayBuffer());
    assert.equal(bytes.length, file.info.size);
    assert.equal(crypto.createHash('sha512').update(bytes).digest('base64'), file.info.sha512);
    const mapResponse = await net.fetch(file.url.href + '.blockmap');
    const blockmap = JSON.parse(zlib.gunzipSync(Buffer.from(await mapResponse.arrayBuffer())));
    const logger = { info() {}, warn() {}, debug() {} };
    const operations = computeOperations(blockmap, blockmap, logger);
    assert.deepEqual(operations, [{ kind: OperationKind.COPY, start: 0, end: bytes.length }]);
    const changed = structuredClone(blockmap);
    changed.files[0].checksums[0] = 'changed';
    assert.deepEqual(computeOperations(blockmap, changed, logger), [{ kind: OperationKind.DOWNLOAD, start: 0, end: bytes.length }]);
    return result.updateInfo.version;
  } finally {
    await new Promise((resolve, reject) => server.close(error => error ? reject(error) : resolve()));
  }
};
