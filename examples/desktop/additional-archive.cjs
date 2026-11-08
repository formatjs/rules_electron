const fs = require('node:fs');
const path = require('node:path');

module.exports = {
  answer: require('./addon.node').answer,
  notice: fs.readFileSync(path.join(__dirname, 'notice.txt'), 'utf8'),
  label: 'shared-asar-ready',
};
