/**
 * Offline tests: loads src/*.js into a sandbox with fake Google services
 * (sheet, properties, Telegram over UrlFetchApp). Run: node tests/run.js
 */
const fs = require('fs');
const path = require('path');
const vm = require('vm');
const assert = require('assert');

function formatDate(date, tz, pattern) {
  const parts = {};
  new Intl.DateTimeFormat('en-GB', {
    timeZone: tz, year: 'numeric', month: '2-digit', day: '2-digit', hour: '2-digit', hourCycle: 'h23',
  }).formatToParts(date).forEach((p) => { parts[p.type] = p.value; });
  return pattern
    .replace('yyyy', parts.year).replace('MM', parts.month).replace('dd', parts.day)
    .replace('H', String(Number(parts.hour)));
}

function makeSandbox(rows) {
  const props = {};
  const sent = [];
  const pendingUpdates = [];
  const grid = [['ID', 'Имя', 'Дата рождения', 'Кто', 'Заметка']].concat(rows || []);

  const range = (r, c, nr = 1, nc = 1) => ({
    getValues: () => Array.from({ length: nr }, (_, i) =>
      Array.from({ length: nc }, (_, j) => ((grid[r - 1 + i] || [])[c - 1 + j] ?? ''))),
    setValues(vals) {
      vals.forEach((row, i) => row.forEach((v, j) => {
        while (grid.length < r + i) grid.push([]);
        grid[r - 1 + i][c - 1 + j] = v;
      }));
      return this;
    },
    setValue(v) { return this.setValues([[v]]); },
    setNumberFormat() { return this; },
    setFontWeight() { return this; },
  });
  const sheet = {
    getRange: range,
    getLastRow: () => grid.length,
    getMaxRows: () => 1000,
    setFrozenRows() {},
    deleteRow: (r) => grid.splice(r - 1, 1),
  };

  const sandbox = {
    console,
    PropertiesService: { getScriptProperties: () => ({
      getProperty: (k) => (k in props ? props[k] : null),
      setProperty: (k, v) => { props[k] = String(v); },
      deleteProperty: (k) => { delete props[k]; },
    }) },
    SpreadsheetApp: { getActiveSpreadsheet: () => ({
      getSheetByName: () => sheet,
      getSpreadsheetTimeZone: () => 'Europe/Moscow',
    }) },
    Utilities: { formatDate, getUuid: () => '12345678-aaaa-bbbb-cccc-1234567890ab' },
    LockService: { getScriptLock: () => ({ tryLock: () => true, releaseLock() {} }) },
    Logger: { log() {} },
    UrlFetchApp: { fetch(url, opts) {
      const method = url.split('/').pop();
      const payload = JSON.parse(opts.payload);
      let result = true;
      if (method === 'getUpdates') result = pendingUpdates.splice(0).filter((u) => u.update_id >= payload.offset);
      else sent.push({ method, ...payload });
      return { getContentText: () => JSON.stringify({ ok: true, result }) };
    } },
  };
  vm.createContext(sandbox);
  for (const f of fs.readdirSync(path.join(__dirname, '../src')).sort()) {
    vm.runInContext(fs.readFileSync(path.join(__dirname, '../src', f), 'utf8'), sandbox, { filename: f });
  }
  let updateId = 1;
  return {
    sb: sandbox, props, sent, grid,
    setNow(iso) { sandbox.now_ = () => new Date(iso); },
    say(text, chatId = 42) {
      pendingUpdates.push({ update_id: updateId++, message: { chat: { id: chatId }, text } });
      sent.length = 0;
      sandbox.pollUpdates();
      return sent;
    },
    press(data, chatId = 42) {
      pendingUpdates.push({ update_id: updateId++, callback_query: { id: 'cb', data, message: { chat: { id: chatId }, message_id: 7 } } });
      sent.length = 0;
      sandbox.pollUpdates();
      return sent;
    },
  };
}

const tests = [];
const test = (name, fn) => tests.push({ name, fn });

test('parseBirthday_ accepts and rejects formats', () => {
  const { sb } = makeSandbox();
  assert.deepStrictEqual({ ...sb.parseBirthday_('12.03.1990', 2026) }, { day: 12, month: 3, year: 1990 });
  assert.deepStrictEqual({ ...sb.parseBirthday_('1/3', 2026) }, { day: 1, month: 3, year: null });
  assert.deepStrictEqual({ ...sb.parseBirthday_('29.02', 2026) }, { day: 29, month: 2, year: null });
  assert.strictEqual(sb.parseBirthday_('29.02.1990', 2026), null);
  assert.strictEqual(sb.parseBirthday_('31.04', 2026), null);
  assert.strictEqual(sb.parseBirthday_('12.13.1990', 2026), null);
  assert.strictEqual(sb.parseBirthday_('12.03.2030', 2026), null);
  assert.strictEqual(sb.parseBirthday_('завтра', 2026), null);
});

test('nextOccurrence_: days left, age, year wrap, 29 Feb', () => {
  const { sb } = makeSandbox();
  const today = { year: 2026, month: 10, day: 26 };
  const n1 = sb.nextOccurrence_({ day: 26, month: 10, year: 1990 }, today);
  assert.strictEqual(n1.daysLeft, 0); assert.strictEqual(n1.age, 36);
  const n2 = sb.nextOccurrence_({ day: 25, month: 10, year: 1990 }, today);
  assert.strictEqual(n2.daysLeft, 364); assert.strictEqual(n2.age, 37);
  const n3 = sb.nextOccurrence_({ day: 29, month: 2, year: null }, { year: 2027, month: 2, day: 28 });
  assert.strictEqual(n3.daysLeft, 0); assert.strictEqual(n3.age, null);
  assert.strictEqual(sb.nextOccurrence_({ day: 29, month: 2, year: null }, { year: 2028, month: 2, day: 28 }).daysLeft, 1);
});

test('plural_ and yearsText_', () => {
  const { sb } = makeSandbox();
  assert.strictEqual(sb.yearsText_(1), '1 год');
  assert.strictEqual(sb.yearsText_(22), '22 года');
  assert.strictEqual(sb.yearsText_(11), '11 лет');
  assert.strictEqual(sb.yearsText_(35), '35 лет');
  assert.strictEqual(sb.whenText_(5), 'через 5 дней');
  assert.strictEqual(sb.whenText_(21), 'через 21 день');
});

test('strangers cannot use the bot; link code binds the owner once', () => {
  const t = makeSandbox();
  t.setNow('2026-10-26T08:00:00Z');
  t.props.BOT_TOKEN = 'x';
  t.props.LINK_CODE = 'secret';
  assert.match(t.say('/list', 42)[0].text, /личный бот/);
  assert.match(t.say('/start wrong', 42)[0].text, /личный бот/);
  assert.match(t.say('/start secret', 42)[0].text, /привязан/);
  assert.strictEqual(t.props.OWNER_CHAT_ID, '42');
  assert.strictEqual(t.props.LINK_CODE, undefined);
  assert.match(t.say('/start secret', 99)[0].text, /личный бот/);
  assert.strictEqual(t.props.OWNER_CHAT_ID, '42');
});

function ownerBot(rows) {
  const t = makeSandbox(rows);
  t.props.BOT_TOKEN = 'x';
  t.props.OWNER_CHAT_ID = '42';
  t.setNow('2026-10-26T06:00:00Z'); // 09:00 Moscow: before the reminder
  return t;
}

test('rows typed into the sheet without ID get IDs', () => {
  const t = ownerBot([['', 'Аня', '05.11', 'друг', ''], ['', 'Боря', '01.01.1980', '', '']]);
  const text = t.say('/list')[0].text;
  assert.match(text, /#1 Аня — 05\.11, через 10 дней/);
  assert.match(text, /#2 Боря — 01\.01, через 67 дней \(47 лет\)/);
  assert.strictEqual(t.grid[1][0], 1);
  assert.strictEqual(t.grid[2][0], 2);
});

test('date cells stored as Date objects are read', () => {
  const t = ownerBot([[1, 'Вера', new Date('1985-11-03T00:00:00+03:00'), '', ''], [2, 'Гена', new Date('2026-12-01T00:00:00+03:00'), '', '']]);
  const text = t.say('/list')[0].text;
  assert.match(text, /Вера — 03\.11, через 8 дней \(41 год\)/);
  assert.match(text, /Гена — 01\.12, через 36 дней$/m); // year equal to current = typed without year
});

test('/add, /edit, find, delete with confirmation', () => {
  const t = ownerBot([[1, 'Аня', '05.11', 'друг', '']]);
  let r = t.say('/add Иван Петров; 12.03.1990; коллега; любит кофе; и чай');
  assert.match(r[0].text, /Добавил[\s\S]*Иван Петров<\/b> \(#2\)[\s\S]*12\.03\.1990[\s\S]*коллега[\s\S]*любит кофе; и чай/);
  assert.deepStrictEqual(t.grid[2], [2, 'Иван Петров', '12.03.1990', 'коллега', 'любит кофе; и чай']);

  assert.match(t.say('/add Иван; 31.02')[0].text, /Не понял дату/);
  assert.match(t.say('/add Иван')[0].text, /Формат/);

  r = t.say('/edit 2 дата 1.4.1991');
  assert.strictEqual(t.grid[2][2], '01.04.1991');
  assert.match(r[0].text, /Сохранил/);
  t.say('/edit 2 Имя Иван Сидоров');
  assert.strictEqual(t.grid[2][1], 'Иван Сидоров');
  assert.match(t.say('/edit 9 имя X')[0].text, /Нет человека с номером 9/);
  assert.match(t.say('/edit 2 возраст 5')[0].text, /Формат/);

  r = t.say('сидоров');
  assert.match(r[0].text, /Иван Сидоров/);
  assert.strictEqual(r[0].reply_markup.inline_keyboard[0][1].callback_data, 'del:2');

  r = t.press('del:2');
  assert.match(r[1].text, /Удалить\?/);
  r = t.press('cancel');
  assert.strictEqual(t.grid.length, 3);
  r = t.press('delok:2');
  assert.strictEqual(t.grid.length, 2);
  assert.match(r.find((m) => m.method === 'editMessageText').text, /Удалил: Иван Сидоров/);
  r = t.press('delok:2');
  assert.match(r.find((m) => m.method === 'editMessageText').text, /уже нет/);
});

test('names are HTML-escaped', () => {
  const t = ownerBot([]);
  const r = t.say('/add <b>Хакер</b> & Co; 01.01');
  assert.match(r[0].text, /&lt;b&gt;Хакер&lt;\/b&gt; &amp; Co/);
});

test('/soon and /today', () => {
  const t = ownerBot([[1, 'Аня', '26.10.2000', '', ''], [2, 'Боря', '20.11', '', ''], [3, 'Вася', '01.06', '', '']]);
  const soon = t.say('/soon')[0].text;
  assert.match(soon, /Аня — 26\.10, сегодня \(26 лет\)/);
  assert.match(soon, /Боря — 20\.11, через 25 дней/);
  assert.doesNotMatch(soon, /Вася/);
  assert.match(t.say('/today')[0].text, /Сегодня<\/b>\n#1 Аня/);
  assert.match(t.say('/soon abc')[0].text, /от 0 до 366/);
});

test('reminder: only from 10:00 Moscow, exactly once a day', () => {
  const t = ownerBot([[1, 'Аня', '26.10.2000', 'сестра', 'позвонить'], [2, 'Боря', '27.10', '', '']]);
  t.setNow('2026-10-26T06:59:00Z'); // 09:59 MSK
  assert.strictEqual(t.say('/help').length, 1);
  t.setNow('2026-10-26T07:00:00Z'); // 10:00 MSK
  const r = t.say('/help');
  assert.strictEqual(r.length, 2);
  assert.strictEqual(r[1].chat_id, '42');
  assert.match(r[1].text, /Сегодня день рождения![\s\S]*Аня<\/b> — 26 лет\n👥 сестра\n📝 позвонить/);
  assert.doesNotMatch(r[1].text, /Боря/);
  t.setNow('2026-10-26T15:00:00Z');
  assert.strictEqual(t.say('/help').length, 1);
  t.setNow('2026-10-27T07:01:00Z');
  assert.match(t.say('/help')[1].text, /Боря/);
});

test('no message on days without birthdays', () => {
  const t = ownerBot([[1, 'Аня', '01.01', '', '']]);
  t.setNow('2026-10-26T08:00:00Z');
  assert.strictEqual(t.say('/help').length, 1);
  assert.strictEqual(t.props.LAST_REMINDER_DATE, '2026-10-26');
});

test('long lists are split into several messages', () => {
  const rows = Array.from({ length: 200 }, (_, i) => [i + 1, 'Человек с длинным именем номер ' + (i + 1), '01.01', 'коллега', '']);
  const t = ownerBot(rows);
  const r = t.say('/list');
  assert.ok(r.length > 1);
  r.forEach((m) => assert.ok(m.text.length <= 4096));
});

test('dist/Code.gs is up to date with src/', () => {
  const { bundle } = require('../tools/bundle.js');
  const built = fs.readFileSync(path.join(__dirname, '../dist/Code.gs'), 'utf8');
  assert.ok(built === bundle(), 'run: node tools/bundle.js');
});

let failed = 0;
for (const { name, fn } of tests) {
  try { fn(); console.log('ok   ' + name); } catch (e) { failed++; console.log('FAIL ' + name + '\n' + e.stack); }
}
console.log(failed ? failed + ' failed' : 'all ' + tests.length + ' passed');
process.exit(failed ? 1 : 0);
