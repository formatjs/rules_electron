import assert from 'node:assert/strict';
import { mkdir, mkdtemp, rm, symlink, writeFile } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { test } from 'node:test';
import { signApp } from './keychain_sign.mjs';

test('signs nested Mach-O code before containing bundles, skips resources and symlinks', async (t) => {
  const root = await mkdtemp(join(tmpdir(), 'keychain-sign-'));
  t.after(() => rm(root, { recursive: true, force: true }));
  const app = join(root, 'Example.app');
  const helper = join(app, 'Contents/Frameworks/Helper.app');
  await mkdir(join(helper, 'Contents/MacOS'), { recursive: true });
  const binary = join(helper, 'Contents/MacOS/helper');
  const header = Buffer.alloc(32);
  header.writeUInt32LE(0xfeedfacf, 0);
  header.writeUInt32LE(2, 12);
  await writeFile(binary, header);
  await writeFile(join(app, 'resource'), 'not executable code');
  await symlink(root, join(app, 'outside'));
  const entitlements = join(root, 'entitlements.plist');
  await writeFile(entitlements, '<plist><dict/></plist>');
  const calls = [];
  await signApp({ app, identity: 'Developer ID Application: Example', keychain: join(root, 'identity.keychain'), entitlements }, async (...args) => calls.push(args));
  assert.deepEqual(calls, [binary, helper, app].map((path) => ['/usr/bin/codesign', [
    '--force', '--sign', 'Developer ID Application: Example', '--options', 'runtime',
    '--timestamp', '--keychain', join(root, 'identity.keychain'), '--entitlements', entitlements, path,
  ]]).concat([['/usr/bin/codesign', ['--verify', '--deep', '--strict', '--verbose=4', app]]]));
  const failure = new Error('signing failed');
  await assert.rejects(signApp({ app, identity: '-' }, async () => { throw failure; }), failure);
});
