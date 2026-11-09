const assert = require('node:assert/strict');
const { statSync } = require('node:fs');
const { app, autoUpdater: nativeUpdater } = require('electron');
const { autoUpdater, MacUpdater } = require('electron-updater');

module.exports = async function macosUpdateSmoke() {
  assert.equal(process.platform, 'darwin');
  if (app.getVersion() === '2.0.0') {
    console.log('MAC_UPDATE_RELAUNCHED');
    setTimeout(() => app.quit(), 120000);
    return;
  }
  assert.equal(app.getVersion(), '1.0.0');
  assert.ok(autoUpdater instanceof MacUpdater);
  const mode = process.env.RULES_ELECTRON_MAC_UPDATE_MODE;
  assert.ok(['hash', 'signature', 'install'].includes(mode));
  const feed = new URL(process.env.RULES_ELECTRON_UPDATE_FEED);
  assert.equal(feed.protocol, 'http:');
  assert.equal(feed.hostname, '127.0.0.1');
  autoUpdater.logger = null;
  autoUpdater.setFeedURL({ provider: 'generic', url: feed.href, useMultipleRangeRequest: false });
  autoUpdater.autoDownload = false;
  autoUpdater.autoInstallOnAppQuit = false;
  autoUpdater.autoRunAppAfterInstall = true;
  autoUpdater.disableDifferentialDownload = true;
  const timer = setTimeout(() => app.exit(1), 120000);
  autoUpdater.on('error', error => {
    if (mode === 'hash') return;
    if (mode === 'signature' && /signature|signed|identity|requirement|trust/i.test(error.message)) {
      clearTimeout(timer);
      console.log('MAC_UPDATE_SIGNATURE_REJECTED');
      app.quit();
    } else {
      console.error(error);
      app.exit(1);
    }
  });
  const result = await autoUpdater.checkForUpdates();
  assert.equal(result.updateInfo.version, '2.0.0');
  assert.equal(result.isUpdateAvailable, true);
  if (mode === 'hash') {
    await assert.rejects(autoUpdater.downloadUpdate(), error => /sha512|checksum/i.test(error.message));
    clearTimeout(timer);
    console.log('MAC_UPDATE_HASH_REJECTED');
    app.quit();
    return;
  }
  const files = await autoUpdater.downloadUpdate();
  assert.equal(files.length, 1);
  assert.ok(files[0].endsWith('.zip'));
  assert.ok(statSync(files[0]).size > 0);
  if (mode === 'signature') {
    nativeUpdater.once('update-downloaded', () => app.exit(1));
  } else {
    app.once('before-quit', () => {
      clearTimeout(timer);
      console.log('MAC_INSTALLED_UPDATE_SMOKE_OK');
    });
  }
  autoUpdater.quitAndInstall();
};
