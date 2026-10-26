/** Joins src/*.js into dist/Code.gs: one file to paste into the Apps Script editor. Run: node tools/bundle.js */
const fs = require('fs');
const path = require('path');

const src = path.join(__dirname, '../src');
const header = '// Собрано из src/ командой `node tools/bundle.js`. Правьте src/, а не этот файл.\n';

function bundle() {
  return header + fs.readdirSync(src).sort()
    .map((f) => '\n// ===== ' + f + ' =====\n\n' + fs.readFileSync(path.join(src, f), 'utf8'))
    .join('');
}

if (require.main === module) {
  fs.writeFileSync(path.join(__dirname, '../dist/Code.gs'), bundle());
  console.log('dist/Code.gs updated');
}
module.exports = { bundle };
