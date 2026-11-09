const { app, BrowserWindow, ipcMain, protocol, shell } = require('electron');
const { execFileSync } = require('node:child_process');
const fs = require('node:fs');
const path = require('node:path');
const assert = require('node:assert/strict');
const appUserModelId = 'org.example.sample-desktop';
if (process.platform === 'win32') app.setAppUserModelId(appUserModelId);
const addon = require('example-native');
const classicAddon = require('example-native/classic.node');
assert.equal(classicAddon.answer(), 42);
assert.deepEqual([...new Uint8Array(classicAddon.backingStore())], [0x12, 0x34, 0x56, 0x78]);
assert.equal(classicAddon.moduleAbi, Number(process.versions.modules));

const smoke = process.argv.includes('--smoke');
const protocolSmokeIndex = process.argv.indexOf('--protocol-smoke');
const protocolReport = protocolSmokeIndex >= 0 ? process.argv[protocolSmokeIndex + 1] : null;
const documentSmokeIndex = process.argv.indexOf('--document-smoke');
const documentReport = documentSmokeIndex >= 0 ? process.argv[documentSmokeIndex + 1] : null;
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

if (documentSmokeIndex >= 0) {
  assert.ok(documentReport && path.isAbsolute(documentReport));
  app.on('open-file', (event, file) => {
    event.preventDefault();
    fs.writeFileSync(documentReport, JSON.stringify({
      file, content: fs.readFileSync(file, 'utf8'), platform: process.platform, architecture: process.arch,
    }));
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
  if (process.env.RULES_ELECTRON_FILE_VERB_REPORT) {
    const argument = process.argv.find((value) => value.startsWith('--file-association-verb='));
    assert.ok(argument);
    const file = process.argv[process.argv.indexOf(argument) + 1];
    assert.ok(path.isAbsolute(file));
    fs.writeFileSync(process.env.RULES_ELECTRON_FILE_VERB_REPORT, JSON.stringify({
      verb: argument.split('=')[1], file, content: fs.readFileSync(file, 'utf8'), architecture: process.arch,
    }));
    app.quit();
    return;
  }
  if (protocolReport || documentReport) {
    fs.writeFileSync((protocolReport || documentReport) + '.ready', 'ready');
    watchdog = setTimeout(() => app.exit(1), 20000);
    return;
  }
  if (process.argv.includes('--mac-update-smoke')) {
    await require('./macos-update-smoke.cjs')();
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
      assert.throws(() => require('example-native/bad-abi.node'), /NODE_MODULE_VERSION 139/);
      const { Worker } = require('node:worker_threads');
      const workerReport = await new Promise((resolve, reject) => {
        let report;
        const worker = new Worker(`
          const { parentPort, workerData } = require('node:worker_threads');
          const addon = require(workerData);
          parentPort.postMessage({ answer: addon.answer(), moduleAbi: addon.moduleAbi,
            backingStore: [...new Uint8Array(addon.backingStore())] });
        `, { eval: true, workerData: require.resolve('example-native/classic.node'), execArgv: [], env: {} });
        worker.once('message', (value) => { report = value; });
        worker.once('error', reject);
        worker.once('exit', (code) => code === 0 ? resolve(report) : reject(new Error('Native addon worker failed')));
      });
      assert.deepEqual(workerReport, { answer: 42, moduleAbi: Number(process.versions.modules),
        backingStore: [0x12, 0x34, 0x56, 0x78] });
      assert.deepEqual(result, {
        message: 'Hello from extra resources',
        asset: 'Hello, 世界',
        answer: 42,
        helper: 'native helper ready',
      });
      assert.equal(app.isPackaged, true);
      assert.deepEqual(fs.readdirSync(path.join(__dirname, 'renderer/empty')), []);
      assert.equal(fs.readFileSync(path.join(__dirname, 'renderer/page.html'), 'utf8'),
        fs.readFileSync(path.join(__dirname, 'renderer/index.html'), 'utf8'));
      assert.equal(fs.readFileSync(path.join(__dirname, 'renderer/current/index.js'), 'utf8'),
        fs.readFileSync(path.join(__dirname, 'renderer/index.js'), 'utf8'));
      if (process.windowsStore) {
        assert.equal(fs.existsSync(path.join(process.resourcesPath, 'directories/empty')), false);
      } else {
        assert.deepEqual(fs.readdirSync(path.join(process.resourcesPath, 'directories/empty')), []);
      }
      if (process.platform === 'darwin') {
        assert.equal(fs.lstatSync(path.join(process.resourcesPath, 'linked-config')).isSymbolicLink(), true);
        assert.equal(fs.lstatSync(path.join(process.resourcesPath, 'nested/config')).isSymbolicLink(), true);
        assert.equal(fs.realpathSync(path.join(process.resourcesPath, 'nested/config/settings.json')),
          fs.realpathSync(path.join(process.resourcesPath, 'config/settings.json')));
      }
      assert.equal(fs.readFileSync(path.join(path.dirname(process.resourcesPath), 'licenses/NOTICE.txt'), 'utf8'),
        'Generic desktop example notice.\n');
      if (process.platform !== 'win32') {
        const licenses = path.join(path.dirname(process.resourcesPath), 'licenses');
        assert.ok(fs.lstatSync(path.join(licenses, 'current')).isSymbolicLink());
        assert.equal(fs.readFileSync(path.join(licenses, 'current/notice-alias.txt'), 'utf8'),
          'Generic desktop example notice.\n');
        for (const root of [path.join(process.resourcesPath, 'generated'),
          path.join(path.dirname(process.resourcesPath), 'generated-files')]) {
          const renderer = path.join(root, 'renderer');
          assert.ok(fs.lstatSync(path.join(renderer, 'page.html')).isSymbolicLink());
          assert.ok(fs.lstatSync(path.join(renderer, 'current')).isSymbolicLink());
          assert.equal(fs.realpathSync(path.join(renderer, 'current/page.html')),
            fs.realpathSync(path.join(renderer, 'index.html')));
          assert.equal(fs.readFileSync(path.join(renderer, 'current/page.html'), 'utf8'),
            fs.readFileSync(path.join(__dirname, 'renderer/index.html'), 'utf8'));
          assert.deepEqual(fs.readdirSync(path.join(renderer, 'current/empty')), []);
          assert.equal(fs.existsSync(path.join(renderer, 'development.map')), false);
          assert.equal(fs.existsSync(path.join(renderer, 'development.txt')), false);
        }
      }
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
      if (process.platform === 'win32') {
        assert.equal(addon.appUserModelId, appUserModelId);
        process.argv.forEach((argument, index) => {
          if (argument !== '--shortcut-smoke') return;
          const details = shell.readShortcutLink(process.argv[index + 1]);
          assert.equal(details.target.toLowerCase(), process.execPath.toLowerCase());
          assert.equal(details.appUserModelId, appUserModelId);
        });
      }
      assert.equal(require('./package.json').scripts, undefined);
      assert.equal(require('./package.json').devDependencies, undefined);
      assert.equal(fs.existsSync(path.join(__dirname, 'node_modules/minimatch/package.json')), false);
      assert.deepEqual(require('./package.json').dependencies, {
        'example-native': '1.0.0', 'electron-updater': '6.8.11',
      });
      assert.deepEqual(require('./package.json').releaseMetadata, {
        channel: 'stable', features: ['native-addon', 'updater'],
      });
      const environment = await window.webContents.executeJavaScript('({node: typeof require, bridge: typeof window.desktop.read, ...window.desktop.environment})');
      assert.deepEqual(environment, { node: 'undefined', bridge: 'function', sandboxed: true, contextIsolated: true });
      const update_version = process.windowsStore ? null : await require('./updater-smoke.cjs')();
      clearTimeout(watchdog);
      console.log('EXAMPLE_SMOKE_OK ' + JSON.stringify({ ...result, architecture: process.arch, platform: process.platform, update_version, app_version: app.getVersion(), windows_store: Boolean(process.windowsStore), classic_module_abi: classicAddon.moduleAbi }));
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
