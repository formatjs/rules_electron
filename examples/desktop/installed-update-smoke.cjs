const assert = require('node:assert/strict');
const { app } = require('electron');
const { autoUpdater, DebUpdater, NsisUpdater } = require('electron-updater');

// Installed-app CI path. Uses the real downloader and platform installer.
module.exports = async function installUpdate(expectFailure) {
  assert.ok(['linux', 'win32'].includes(process.platform));
  assert.equal(app.getVersion(), '1.0.0');
  assert.ok(autoUpdater instanceof (process.platform === 'win32' ? NsisUpdater : DebUpdater));
  const feed = new URL(process.env.RULES_ELECTRON_UPDATE_FEED);
  assert.equal(feed.protocol, 'http:');
  assert.equal(feed.hostname, '127.0.0.1');
  autoUpdater.setFeedURL({ provider: 'generic', url: feed.href, useMultipleRangeRequest: false });
  autoUpdater.disableDifferentialDownload = expectFailure;
  autoUpdater.autoDownload = false;
  autoUpdater.autoInstallOnAppQuit = false;
  autoUpdater.autoRunAppAfterInstall = false;
  autoUpdater.on('error', error => { if (!expectFailure) { console.error(error); app.exit(1); } });
  const timer = setTimeout(() => app.exit(1), 90000);
  const result = await autoUpdater.checkForUpdates();
  assert.equal(result.updateInfo.version, '2.0.0');
  assert.equal(result.isUpdateAvailable, true);
  if (expectFailure) {
    await assert.rejects(autoUpdater.downloadUpdate(), error => /sha512|checksum/i.test(error.message));
    clearTimeout(timer);
    console.log('UPDATE_HASH_REJECTED');
    app.quit();
    return;
  }
  const files = await autoUpdater.downloadUpdate();
  assert.equal(files.length, 1);
  app.on('before-quit', () => {
    clearTimeout(timer);
    console.log('INSTALLED_UPDATE_SMOKE_OK');
  });
  autoUpdater.quitAndInstall(true, false);
};
