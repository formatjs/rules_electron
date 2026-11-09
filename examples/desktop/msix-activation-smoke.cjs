const assert = require('node:assert/strict');
const fs = require('node:fs');
const os = require('node:os');
const path = require('node:path');
const { app } = require('electron');

// Reports require an exclusive host-created marker and nonce directory.
module.exports = function checkActivation() {
  const markerPath = path.join(os.tmpdir(), 'rules-electron-msix-activation.json');
  if (!fs.existsSync(markerPath)) return false;
  const { nonce } = JSON.parse(fs.readFileSync(markerPath, 'utf8'));
  assert.match(nonce, /^[a-f0-9]{32}$/);
  const directory = path.join(os.tmpdir(), `rules-electron-msix-${nonce}`);
  const request = JSON.parse(fs.readFileSync(path.join(directory, 'request.json'), 'utf8'));
  const report = path.join(directory, 'report.json');
  const write = (value) => {
    fs.writeFileSync(report + '.tmp', JSON.stringify(value), { flag: 'wx' });
    fs.renameSync(report + '.tmp', report);
  };
  const uri = process.argv.find(value => /^sample-msix(?:-alt)?:\/\/activation-smoke\/[a-f0-9]{32}$/.test(value));
  const file = process.argv.find(value => /\.samplemsix(?:_alt)?$/.test(value));
  let stage = 'argument';
  try {
    assert.ok(uri || file);
    assert.equal(request.nonce, nonce);
    stage = 'kind';
    assert.equal(request.kind, uri ? 'protocol' : 'file');
    stage = 'value';
    assert.equal(request.value, uri || file);
    stage = 'identity';
    assert.equal(process.windowsStore, true);
    assert.equal(app.isPackaged, true);
    stage = 'directory';
    if (file) assert.equal(fs.realpathSync.native(path.dirname(file)).toLowerCase(),
      fs.realpathSync.native(directory).toLowerCase());
    stage = 'content';
    const content = file ? fs.readFileSync(file, 'utf8') : null;
    write({
      kind: request.kind, value: uri || file, nonce, content,
      architecture: process.arch, version: app.getVersion(), pid: process.pid,
      executable: fs.realpathSync.native(process.execPath),
      windows_store: Boolean(process.windowsStore), packaged: app.isPackaged,
    });
  } catch {
    write({ failure: stage, arguments: process.argv.slice(1).map(value => ({
      absolute: path.isAbsolute(value), file_uri: value.startsWith('file:'),
      document_suffix: /\.samplemsix(?:_alt)?$/.test(value),
      contains_nonce: value.includes(nonce), quoted: value.startsWith('"') || value.endsWith('"'),
      escaped: /%[a-f0-9]{2}/i.test(value),
      placeholder: value.includes('%1'), server_name: value.startsWith('-ServerName'),
      same_ignore_case: value.toLowerCase() === request.value.toLowerCase(),
    })) });
    app.exit(1);
  }
  return true;
};
