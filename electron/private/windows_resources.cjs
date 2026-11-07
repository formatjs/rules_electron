const fs = require('node:fs');
const path = require('node:path');
const { createRequire } = require('node:module');

const [modules, binary, encoded] = process.argv.slice(2);
const load = createRequire(path.join(path.resolve(modules), 'resolve.cjs'));
const { NtExecutable, NtExecutableResource } = load('pe-library');
const { Resource } = load('resedit');
const options = JSON.parse(encoded);
const number = '(?:0|[1-9][0-9]*)';
const identifier = '(?:0|[1-9][0-9]*|[0-9]*[A-Za-z-][A-Za-z0-9-]*)';
const version = new RegExp(`^(${number})\\.(${number})\\.(${number})(?:-${identifier}(?:\\.${identifier})*)?(?:\\+[A-Za-z0-9-]+(?:\\.[A-Za-z0-9-]+)*)?$`).exec(options.version);
if (!version || version.slice(1).some((part) => Number(part) > 65535)) {
  throw new Error('Windows version needs SemVer with numeric components in 0..65535');
}
const allowed = ['CompanyName', 'FileDescription', 'InternalName', 'LegalCopyright', 'OriginalFilename', 'ProductName'];
for (const [key, value] of Object.entries(options.metadata)) {
  if (!allowed.includes(key) || typeof value !== 'string' || value.includes('\0')) {
    throw new Error(`Invalid Windows metadata: ${key}`);
  }
}
if (options.header_hash && !/^[a-f0-9]{64}$/.test(options.header_hash)) {
  throw new Error('Invalid ASAR header SHA-256');
}

// Resource changes invalidate the runtime's old signature; release signing follows.
const executable = NtExecutable.from(fs.readFileSync(binary), { ignoreCert: true });
const resources = NtExecutableResource.from(executable);
const versions = Resource.VersionInfo.fromEntries(resources.entries);
if (versions.length !== 1) throw new Error('Expected one Windows version resource');
const info = versions[0];
const languages = info.getAllLanguagesForStringValues();
if (languages.length !== 1) throw new Error('Expected one Windows resource language');
const language = languages[0];
const numeric = version.slice(1).map(Number);
info.setFileVersion(...numeric, 0, language.lang);
info.setProductVersion(...numeric, 0, language.lang);
info.setStringValues(language, {
  ProductName: options.product_name,
  FileDescription: options.product_name,
  InternalName: options.executable_name,
  OriginalFilename: path.basename(binary),
  ...options.metadata,
  FileVersion: options.version,
  ProductVersion: options.version,
});
info.outputToResourceEntries(resources.entries);

resources.entries = resources.entries.filter((entry) => String(entry.type).toUpperCase() !== 'INTEGRITY' || String(entry.id).toUpperCase() !== 'ELECTRONASAR');
if (options.header_hash) {
  resources.entries.push({
    type: 'INTEGRITY',
    id: 'ELECTRONASAR',
    lang: language.lang,
    codepage: language.codepage,
    bin: new TextEncoder().encode(JSON.stringify([
      { file: 'resources\\app.asar', alg: 'SHA256', value: options.header_hash },
    ])).buffer,
  });
}
resources.outputResource(executable);
fs.writeFileSync(binary, Buffer.from(executable.generate()));
