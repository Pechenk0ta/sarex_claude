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

/** Same code with the bot token written in. The result is personal: never commit it. */
function withToken(code, token) {
  const marker = "const BOT_TOKEN_IN_CODE = '';";
  if (!code.includes(marker)) throw new Error('BOT_TOKEN_IN_CODE not found');
  if (!/^\d+:[\w-]+$/.test(token)) throw new Error('This does not look like a bot token');
  return code.replace(marker, "const BOT_TOKEN_IN_CODE = '" + token + "';");
}

// node tools/bundle.js                → dist/Code.gs (no token, for git)
// node tools/bundle.js TOKEN OUT_FILE → personal copy with the token, outside git
if (require.main === module) {
  const [token, out] = process.argv.slice(2);
  if (token) {
    fs.writeFileSync(out, withToken(bundle(), token));
    console.log(out + ' written');
  } else {
    fs.writeFileSync(path.join(__dirname, '../dist/Code.gs'), bundle());
    console.log('dist/Code.gs updated');
  }
}
module.exports = { bundle, withToken };
