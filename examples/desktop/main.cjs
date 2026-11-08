const { app, BrowserWindow, ipcMain, protocol } = require('electron');
const { execFileSync } = require('node:child_process');
const fs = require('node:fs');
const path = require('node:path');
const assert = require('node:assert/strict');
const addon = require('example-native');

const smoke = process.argv.includes('--smoke');
const protocolSmokeIndex = process.argv.indexOf('--protocol-smoke');
const protocolReport = protocolSmokeIndex >= 0 ? process.argv[protocolSmokeIndex + 1] : null;
let window;
let watchdog;

if (protocolSmokeIndex >= 0) {
  assert.ok(protocolReport && path.isAbsolute(protocolReport));
  app.on('open-url', (event, url) => {
    event.preventDefault();
    fs.writeFileSync(protocolReport, JSON.stringify({ url, platform: process.platform, architecture: process.arch }));
    app.quit();
  });
}

protocol.registerSchemesAsPrivileged([
  { scheme: 'sample', privileges: { standard: true, secure: true, supportFetchAPI: true } },
]);

function ownFrame(event) {
  return event.sender === window.webContents && event.senderFrame === window.webContents.mainFrame;
}

app.whenReady().then(async () => {
  if (protocolReport) {
    fs.writeFileSync(protocolReport + '.ready', 'ready');
    watchdog = setTimeout(() => app.exit(1), 20000);
    return;
  }
  if (process.argv.includes('--install-update-smoke') || process.argv.includes('--reject-update-smoke')) {
    await require('./installed-update-smoke.cjs')(process.argv.includes('--reject-update-smoke'));
    return;
  }
  const rendererFiles = {
    '/index.html': ['index.html', 'text/html; charset=utf-8'],
    '/index.js': ['index.js', 'text/javascript; charset=utf-8'],
    '/style.css': ['style.css', 'text/css; charset=utf-8'],
  };
  protocol.handle('sample', (request) => {
    const url = new URL(request.url);
    const file = Object.hasOwn(rendererFiles, url.pathname) && rendererFiles[url.pathname];
    if (url.host !== 'app' || request.method !== 'GET' || !file) return new Response(null, { status: 404 });
    return new Response(fs.readFileSync(path.join(__dirname, 'renderer', file[0])), {
      headers: { 'Content-Type': file[1] },
    });
  });
  window = new BrowserWindow({
    width: 720,
    height: 480,
    show: !smoke,
    webPreferences: {
      preload: path.join(__dirname, 'preload.cjs'),
      contextIsolation: true,
      nodeIntegration: false,
      sandbox: true,
    },
  });
  window.webContents.setWindowOpenHandler(() => ({ action: 'deny' }));
  window.webContents.on('will-navigate', (event) => event.preventDefault());
  ipcMain.handle('example:read', (event) => {
    if (!ownFrame(event)) throw new Error('Unexpected IPC sender');
    const settings = JSON.parse(fs.readFileSync(path.join(process.resourcesPath, 'config/settings.json')));
    const asset = require('./assets/message.json');
    const helperName = process.platform === 'win32' ? 'helper.exe' : 'helper';
    const helper = JSON.parse(execFileSync(path.join(process.resourcesPath, 'native', helperName), { encoding: 'utf8' }));
    return {
      message: settings.message,
      asset: asset.message,
      answer: addon.answer,
      helper: helper.message,
    };
  });
  ipcMain.on('example:complete', async (event, result) => {
    if (!ownFrame(event) || !smoke) return;
    try {
      assert.deepEqual(result, {
        message: 'Hello from extra resources',
        asset: 'Hello, 世界',
        answer: 42,
        helper: 'native helper ready',
      });
      assert.equal(app.isPackaged, true);
      assert.equal(fs.readFileSync(path.join(path.dirname(process.resourcesPath), 'licenses/NOTICE.txt'), 'utf8'),
        'Generic desktop example notice.\n');
      assert.equal(path.basename(__filename), 'main.cjs');
      assert.equal(fs.existsSync(path.join(__dirname, 'renderer/development.map')), false);
      assert.equal(fs.existsSync(path.join(__dirname, 'renderer/development.txt')), false);
      assert.ok(fs.lstatSync(path.join(__dirname, 'linked-main.cjs')).isSymbolicLink());
      assert.deepEqual(JSON.parse(fs.readFileSync(path.join(__dirname, 'linked-assets/message.json'), 'utf8')),
        require('./assets/message.json'));
      const shared = path.join(process.resourcesPath, 'plugins/shared.asar');
      assert.ok(fs.lstatSync(path.join(shared, 'entry-chain.cjs')).isSymbolicLink());
      assert.equal(fs.realpathSync(path.join(shared, 'entry-chain.cjs')), path.join(shared, 'index.cjs'));
      assert.deepEqual(require(path.join(shared, 'entry-chain.cjs')), {
        answer: 42,
        notice: 'Generic desktop example notice.\n',
        label: 'shared-asar-ready',
      });
      assert.ok(app.getAppPath().endsWith('app.asar'));
      assert.equal(require('./package.json').scripts, undefined);
      const environment = await window.webContents.executeJavaScript('({node: typeof require, bridge: typeof window.desktop.read, ...window.desktop.environment})');
      assert.deepEqual(environment, { node: 'undefined', bridge: 'function', sandboxed: true, contextIsolated: true });
      const update_version = await require('./updater-smoke.cjs')();
      clearTimeout(watchdog);
      console.log('EXAMPLE_SMOKE_OK ' + JSON.stringify({ ...result, architecture: process.arch, platform: process.platform, update_version, app_version: app.getVersion() }));
      app.quit();
    } catch (error) {
      console.error(error);
      app.exit(1);
    }
  });
  if (smoke) watchdog = setTimeout(() => app.exit(1), 20000);
  await window.loadURL('sample://app/index.html');
}).catch((error) => {
  console.error(error);
  app.exit(1);
});

app.on('window-all-closed', () => app.quit());
