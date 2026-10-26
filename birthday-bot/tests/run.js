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

function makeSandbox(rows, tokenInCode) {
  const props = {};
  const sent = [];
  const pendingUpdates = [];
  const grid = [['№', 'TASK', 'Должность', 'День рождения', '']].concat(rows || []);

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
      getSheetByName: () => null,
      getSheets: () => [sheet],
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
  const { bundle, withToken } = require('../tools/bundle.js');
  const code = bundle();
  vm.runInContext(tokenInCode ? withToken(code, tokenInCode) : code, sandbox, { filename: 'Code.gs' });
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
  assert.deepStrictEqual({ ...sb.parseBirthday_('16.09.1900', 2026) }, { day: 16, month: 9, year: null });
  assert.strictEqual(sb.parseBirthday_('16.09.1899', 2026), null);
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

test('rows typed into the sheet without № get numbers', () => {
  const t = ownerBot([['', 'Аня', '', '05.11', ''], ['', 'Боря', 'Архитектор', '01.01.1980', 'Absolut']]);
  const text = t.say('/list')[0].text;
  assert.match(text, /#1 Аня — 05\.11, через 10 дней/);
  assert.match(text, /#2 Боря — 01\.01, через 67 дней \(47 лет\)/);
  assert.strictEqual(t.grid[1][0], 1);
  assert.strictEqual(t.grid[2][0], 2);
});

test('date cells stored as Date objects or serial numbers are read', () => {
  const t = ownerBot([
    [1, 'Вера', '', new Date('1985-11-03T00:00:00+03:00'), ''],
    [2, 'Гена', '', new Date('2026-12-01T00:00:00+03:00'), ''],
    [3, 'Даша', '', 33360, ''], // 02.05.1991
  ]);
  const text = t.say('/list')[0].text;
  assert.match(text, /Вера — 03\.11, через 8 дней \(41 год\)/);
  assert.match(text, /Гена — 01\.12, через 36 дней$/m); // year equal to current = typed without year
  assert.match(text, /Даша — 02\.05, через 188 дней \(36 лет\)/);
});

test('/add (date in any position), /edit, find, delete with confirmation', () => {
  const t = ownerBot([[1, 'Сергеев Сергей Сергеевич', 'Генеральный директор', '02.05.1991', 'Absolut']]);
  let r = t.say('/add Иванов Иван Иванович; Менеджер продукта; 12.03.1990; Absolut');
  assert.match(r[0].text, /Добавил[\s\S]*Иванов Иван Иванович<\/b> \(#2\)[\s\S]*12\.03\.1990[\s\S]*💼 Менеджер продукта, Absolut/);
  assert.deepStrictEqual(t.grid[2], [2, 'Иванов Иван Иванович', 'Менеджер продукта', '12.03.1990', 'Absolut']);
  t.say('/add Петров Пётр; 01.02');
  assert.deepStrictEqual(t.grid[3], [3, 'Петров Пётр', '', '01.02', '']);
  t.say('/delete 3'); t.press('delok:3');

  assert.match(t.say('/add Иван; 31.02')[0].text, /Не нашёл дату/);
  assert.match(t.say('/add Иван')[0].text, /Формат/);

  r = t.say('/edit 2 дата 1.4.1991');
  assert.strictEqual(t.grid[2][3], '01.04.1991');
  assert.match(r[0].text, /Сохранил/);
  t.say('/edit 2 ФИО Иванов Иван Петрович');
  assert.strictEqual(t.grid[2][1], 'Иванов Иван Петрович');
  t.say('/edit 2 должность Архитектор');
  assert.strictEqual(t.grid[2][2], 'Архитектор');
  t.say('/edit 2 компания Absolut Страхование');
  assert.strictEqual(t.grid[2][4], 'Absolut Страхование');
  assert.match(t.say('/edit 9 фио X')[0].text, /Нет человека с номером 9/);
  assert.match(t.say('/edit 2 возраст 5')[0].text, /Формат/);

  r = t.say('архитектор');
  assert.match(r[0].text, /Иванов Иван Петрович/);
  assert.strictEqual(r[0].reply_markup.inline_keyboard[0][1].callback_data, 'del:2');

  r = t.press('del:2');
  assert.match(r[1].text, /Удалить\?/);
  t.press('cancel');
  assert.strictEqual(t.grid.length, 3);
  r = t.press('delok:2');
  assert.strictEqual(t.grid.length, 2);
  assert.match(r.find((m) => m.method === 'editMessageText').text, /Удалил: Иванов Иван Петрович/);
  r = t.press('delok:2');
  assert.match(r.find((m) => m.method === 'editMessageText').text, /уже нет/);
});

test('names are HTML-escaped', () => {
  const t = ownerBot([]);
  const r = t.say('/add <b>Хакер</b> & Co; 01.01');
  assert.match(r[0].text, /&lt;b&gt;Хакер&lt;\/b&gt; &amp; Co/);
});

test('/soon and /today', () => {
  const t = ownerBot([[1, 'Аня', '', '26.10.2000', ''], [2, 'Боря', '', '20.11', ''], [3, 'Вася', '', '01.06', '']]);
  const soon = t.say('/soon')[0].text;
  assert.match(soon, /Аня — 26\.10, сегодня \(26 лет\)/);
  assert.match(soon, /Боря — 20\.11, через 25 дней/);
  assert.doesNotMatch(soon, /Вася/);
  assert.match(t.say('/today')[0].text, /Сегодня<\/b>\n#1 Аня/);
  assert.match(t.say('/soon abc')[0].text, /от 0 до 366/);
});

test('reminder: only from 10:00 Moscow, exactly once a day', () => {
  const t = ownerBot([
    [12, 'Смирнова Ольга Петровна', 'Руководитель отдела', '26.10.1988', 'Absolut'],
    [13, 'Боря', '', '27.10.1900', ''],
  ]);
  t.setNow('2026-10-26T06:59:00Z'); // 09:59 MSK
  assert.strictEqual(t.say('/help').length, 1);
  t.setNow('2026-10-26T07:00:00Z'); // 10:00 MSK
  const r = t.say('/help');
  assert.strictEqual(r.length, 2);
  assert.strictEqual(r[1].chat_id, '42');
  assert.match(r[1].text, /Сегодня день рождения!\n\n<b>Смирнова Ольга Петровна<\/b> — 38 лет\n💼 Руководитель отдела, Absolut$/);
  t.setNow('2026-10-26T15:00:00Z');
  assert.strictEqual(t.say('/help').length, 1);
  t.setNow('2026-10-27T07:01:00Z');
  assert.match(t.say('/help')[1].text, /<b>Боря<\/b>$/); // year 1900 = unknown: no age
});

test('no message on days without birthdays', () => {
  const t = ownerBot([[1, 'Аня', '', '01.01', '']]);
  t.setNow('2026-10-26T08:00:00Z');
  assert.strictEqual(t.say('/help').length, 1);
  assert.strictEqual(t.props.LAST_REMINDER_DATE, '2026-10-26');
});

test('token from code is used when Script Properties have none', () => {
  for (const token of [undefined, '123:abc-DEF_1']) {
    const t = makeSandbox([], token);
    t.props.OWNER_CHAT_ID = '42';
    t.setNow('2026-10-26T06:00:00Z');
    if (token) assert.strictEqual(t.say('/help').length, 1);
    else assert.throws(() => t.say('/help'), /Не задан токен/);
  }
});

test('long lists are split into several messages', () => {
  const rows = Array.from({ length: 200 }, (_, i) => [i + 1, 'Человек с длинным именем номер ' + (i + 1), 'Менеджер продукта', '01.01', 'Absolut']);
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
