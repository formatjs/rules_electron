const fs = require('node:fs');
const path = require('node:path');
const { Minimatch } = require(path.join(path.resolve(process.argv[2]), 'node_modules/minimatch'));
const { files, patterns } = JSON.parse(fs.readFileSync(0, 'utf8'));
if (!Array.isArray(files) || !Array.isArray(patterns) ||
    [...files, ...patterns].some((value) => typeof value !== 'string' || value.includes('\0'))) {
  throw new Error('Expected file and pattern string arrays');
}
const matchers = [];
for (const pattern of patterns) {
  const matcher = new Minimatch(pattern, { dot: true, magicalBraces: true });
  matchers.push(matcher);
  if (!matcher.hasMagic()) {
    matchers.push(new Minimatch(`${pattern}/**/*`, { dot: true }));
  }
}
const selected = files.filter((file) => matchers.reduce(
  (matched, matcher) => matched === matcher.negate ? matcher.match(file) : matched, false,
));
process.stdout.write(JSON.stringify(selected));
