const { app } = require('electron');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');

app.whenReady().then(() => {
  assert.equal(app.isPackaged, true);
  assert.equal(app.getAppPath(), path.join(process.resourcesPath, 'app'));
  assert.equal(fs.existsSync(path.join(process.resourcesPath, 'app.asar')), false);
  const renderer = path.join(app.getAppPath(), 'renderer');
  assert.ok(fs.lstatSync(path.join(renderer, 'page.html')).isSymbolicLink());
  assert.ok(fs.lstatSync(path.join(renderer, 'current')).isSymbolicLink());
  assert.equal(fs.realpathSync(path.join(renderer, 'current/page.html')),
    fs.realpathSync(path.join(renderer, 'index.html')));
  assert.equal(fs.readFileSync(path.join(renderer, 'current/page.html'), 'utf8'),
    fs.readFileSync(path.join(renderer, 'index.html'), 'utf8'));
  assert.deepEqual(fs.readdirSync(path.join(renderer, 'current/empty')), []);
  assert.equal(fs.existsSync(path.join(renderer, 'development.map')), false);
  assert.equal(fs.existsSync(path.join(renderer, 'development.txt')), false);
  console.log('PLAIN_LINKS_SMOKE_OK ' + JSON.stringify({ platform: process.platform, architecture: process.arch }));
  app.quit();
}).catch(error => {
  console.error(error);
  app.exit(1);
});
