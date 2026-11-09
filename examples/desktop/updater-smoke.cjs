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
  const githubConfig = yaml.load(fs.readFileSync(path.join(process.resourcesPath, 'github-update-smoke.yml'), 'utf8'));
  assert.equal(githubConfig.provider, 'github');
  assert.deepEqual([githubConfig.owner, githubConfig.repo], ['example-org', 'sample-desktop']);
  assert.equal(githubConfig.updaterCacheDirName, config.updaterCacheDirName);
  assert.equal(githubConfig.private ?? false, false);
  const githubPath = `/${githubConfig.owner}/${githubConfig.repo}/releases`;
  const githubApi = `/api/v3/repos/${githubConfig.owner}/${githubConfig.repo}/releases/latest`;
  const directory = path.join(process.resourcesPath, 'update-smoke-feed');
  const requests = [];
  const githubRequests = [];
  const server = http.createServer((request, response) => {
    const pathname = new URL(request.url, 'http://localhost').pathname;
    if (pathname === `${githubPath}.atom`) {
      githubRequests.push(pathname);
      response.setHeader('Content-Type', 'application/atom+xml');
      response.end(`<?xml version="1.0" encoding="UTF-8"?><feed xmlns="http://www.w3.org/2005/Atom">
        <id>urn:rules-electron:releases</id><title>Fixture releases</title><updated>2026-01-02T03:04:05Z</updated>
        <entry><id>urn:rules-electron:v2.0.0</id><title>v2.0.0</title><updated>2026-01-02T03:04:05Z</updated>
        <link href="${githubPath}/tag/v2.0.0"/><content type="text">Public fixture release</content></entry></feed>`);
      return;
    }
    if (pathname === githubApi) {
      githubRequests.push(pathname);
      response.setHeader('Content-Type', 'application/json');
      response.end(JSON.stringify({ tag_name: 'v2.0.0' }));
      return;
    }
    const download = `${githubPath}/download/v2.0.0/`;
    if (pathname.startsWith(download)) githubRequests.push(pathname);
    const name = decodeURIComponent(pathname.startsWith(download) ? pathname.slice(download.length) : pathname.slice(1));
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
    const githubUpdater = new Updater({ ...githubConfig, host: base.host, protocol: 'http' });
    githubUpdater.logger = null;
    githubUpdater.autoDownload = false;
    githubUpdater.autoInstallOnAppQuit = false;
    const githubResult = await githubUpdater.checkForUpdates();
    assert.equal(githubResult.updateInfo.tag, 'v2.0.0');
    assert.equal(githubResult.updateInfo.version, '2.0.0');
    assert.equal(githubResult.isUpdateAvailable, semver.gt('2.0.0', app.getVersion()));
    assert.equal(githubResult.downloadPromise ?? null, null);
    const githubProvider = await githubUpdater.clientPromise;
    assert.equal(githubProvider.constructor.name, 'GitHubProvider');
    const [githubFile] = githubProvider.resolveFiles(githubResult.updateInfo);
    assert.ok(githubFile.url.pathname.startsWith(download));
    const githubBytes = Buffer.from(await (await net.fetch(githubFile.url.href)).arrayBuffer());
    assert.deepEqual(githubBytes, bytes);
    assert.equal(crypto.createHash('sha512').update(githubBytes).digest('base64'), githubFile.info.sha512);
    assert.ok(githubRequests.includes(`${githubPath}.atom`));
    assert.ok(githubRequests.includes(githubApi));
    assert.ok(githubRequests.includes(download + channel));
    console.log('GITHUB_UPDATER_DISCOVERY_OK');
    return result.updateInfo.version;
  } finally {
    await new Promise((resolve, reject) => server.close(error => error ? reject(error) : resolve()));
  }
};
