const assert = require('node:assert/strict');
const fs = require('node:fs');
const os = require('node:os');
const path = require('node:path');
const { app } = require('electron');

// Only fixture inputs with a pre-created nonce directory produce reports.
module.exports = function checkActivation() {
  const uri = process.argv.find(value => /^sample-msix(?:-alt)?:\/\/activation-smoke\/[a-f0-9]{32}$/.test(value));
  const file = process.argv.find(value => /\.samplemsix(?:_alt)?$/.test(value));
  if (!uri && !file) return false;
  const nonce = uri ? new URL(uri).pathname.slice(1) : path.basename(path.dirname(file)).replace(/^rules-electron-msix-/, '');
  if (!/^[a-f0-9]{32}$/.test(nonce)) return false;
  const directory = path.join(os.tmpdir(), `rules-electron-msix-${nonce}`);
  const requestPath = path.join(directory, 'request.json');
  if (!fs.existsSync(requestPath)) return false;
  const request = JSON.parse(fs.readFileSync(requestPath, 'utf8'));
  assert.equal(request.nonce, nonce);
  assert.equal(request.kind, uri ? 'protocol' : 'file');
  assert.equal(request.value, uri || file);
  assert.equal(process.windowsStore, true);
  assert.equal(app.isPackaged, true);
  if (file) assert.equal(path.dirname(file), directory);
  fs.writeFileSync(path.join(directory, 'report.json'), JSON.stringify({
    kind: request.kind, value: uri || file, nonce,
    content: file ? fs.readFileSync(file, 'utf8') : null,
    architecture: process.arch, version: app.getVersion(),
    windows_store: Boolean(process.windowsStore), packaged: app.isPackaged,
  }), { flag: 'wx' });
  return true;
};
