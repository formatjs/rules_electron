import { execFile } from 'node:child_process';
import { open, readdir, stat } from 'node:fs/promises';
import { extname, join, resolve } from 'node:path';
import { pathToFileURL } from 'node:url';
import { parseArgs, promisify } from 'node:util';

const execute = promisify(execFile);

async function executableType(path) {
  const file = await open(path, 'r');
  try {
    const header = Buffer.alloc(16);
    const { bytesRead } = await file.read(header, 0, 16, 0);
    if (bytesRead < 16) return 0;
    const magic = header.readUInt32BE(0);
    if ([0xcafebabe, 0xcafebabf, 0xbebafeca, 0xbfbafeca].includes(magic)) {
      const count = magic === 0xbebafeca || magic === 0xbfbafeca
        ? header.readUInt32LE(4) : header.readUInt32BE(4);
      return count > 0 && count <= 16 ? 2 : 0;
    }
    if (![0xfeedface, 0xfeedfacf, 0xcefaedfe, 0xcffaedfe].includes(magic)) return 0;
    const kind = magic === 0xcefaedfe || magic === 0xcffaedfe
      ? header.readUInt32LE(12) : header.readUInt32BE(12);
    return [2, 6, 8, 9].includes(kind) ? kind : 0;
  } finally {
    await file.close();
  }
}

export async function signApp({ app, identity, keychain, entitlements, entitlementsInherit }, run = execute) {
  app = resolve(app);
  if (!app.endsWith('.app') || !(await stat(app)).isDirectory()) throw new Error('Expected app bundle');
  if (!identity || (identity !== '-' && !keychain)) throw new Error('Expected explicit signing identity and keychain');
  for (const file of [entitlements, entitlementsInherit].filter(Boolean)) {
    if (!(await stat(file)).isFile()) throw new Error('Expected entitlement file');
  }
  const targets = [];
  async function visit(directory) {
    const entries = await readdir(directory, { withFileTypes: true });
    for (const entry of entries.sort((a, b) => a.name.localeCompare(b.name, 'en'))) {
      const path = join(directory, entry.name);
      if (entry.isSymbolicLink()) continue;
      if (entry.isDirectory()) {
        await visit(path);
        if (['.app', '.framework', '.xpc', '.appex'].includes(extname(path))) {
          targets.push(path);
        }
      } else if (entry.isFile()) {
        const kind = await executableType(path);
        if (kind) targets.push(path);
      }
    }
  }
  await visit(app);
  targets.push(app);
  for (const path of targets) {
    const args = ['--force', '--sign', identity, '--options', 'runtime'];
    if (identity !== '-') args.push('--timestamp', '--keychain', resolve(keychain));
    const settings = path === app ? entitlements : (entitlementsInherit || entitlements);
    if (settings) args.push('--entitlements', resolve(settings));
    await run('/usr/bin/codesign', [...args, path]);
  }
  await run('/usr/bin/codesign', ['--verify', '--deep', '--strict', '--verbose=4', app]);
}

if (process.argv[1] && import.meta.url === pathToFileURL(resolve(process.argv[1])).href) {
  const { values } = parseArgs({ options: {
    'check-tools': { type: 'boolean' },
    app: { type: 'string' }, identity: { type: 'string' }, keychain: { type: 'string' },
    entitlements: { type: 'string' }, 'entitlements-inherit': { type: 'string' },
  } });
  if (values['check-tools']) console.log('Electron signing dependencies loaded');
  else await signApp({ ...values, entitlementsInherit: values['entitlements-inherit'] });
}
