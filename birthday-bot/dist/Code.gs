// Собрано из src/ командой `node tools/bundle.js`. Правьте src/, а не этот файл.

// ===== Bot.js =====

/** Handling of incoming Telegram messages and button presses. */

/** A function, not a constant: Apps Script does not guarantee file load order. */
function helpText_() {
  return [
    '<b>Бот напоминаний о днях рождения</b>',
    'Каждый день в ' + REMIND_HOUR + ':00 по Москве пишу, у кого сегодня день рождения.',
    '',
    '<b>Посмотреть</b>',
    '/today — у кого сегодня',
    '/soon — ближайшие ' + SOON_DAYS_DEFAULT + ' дней (/soon 60 — за 60 дней)',
    '/list — все, по ближайшей дате',
    'Просто напишите имя — найду человека и покажу кнопки «Изменить» и «Удалить».',
    '',
    '<b>Добавить</b>',
    '<code>/add Иван Петров; 12.03.1990; коллега; любит кофе</code>',
    'Обязательны имя и дата (год можно не указывать: 12.03). «Кто» и заметка — по желанию.',
    '',
    '<b>Изменить</b> (номер — из /list)',
    '<code>/edit 5 дата 12.03.1991</code>',
    '<code>/edit 5 имя Иван Сидоров</code>',
    '<code>/edit 5 кто друг</code>',
    '<code>/edit 5 заметка подарить книгу</code>',
    '',
    '<b>Удалить</b>',
    '<code>/delete 5</code>',
  ].join('\n');
}

const EDIT_FIELDS = {
  'имя': 'name', 'name': 'name',
  'дата': 'date', 'date': 'date', 'др': 'date',
  'кто': 'group', 'группа': 'group', 'group': 'group',
  'заметка': 'note', 'note': 'note',
};

function handleUpdate_(update) {
  if (update.message) handleMessage_(update.message);
  else if (update.callback_query) handleCallback_(update.callback_query);
}

function isOwner_(chatId) {
  const owner = prop_(P_OWNER);
  return Boolean(owner) && String(chatId) === owner;
}

function handleMessage_(msg) {
  const chatId = msg.chat.id;
  const text = String(msg.text || '').trim();

  if (!isOwner_(chatId)) {
    const code = prop_(P_LINK_CODE);
    if (!prop_(P_OWNER) && code && text === '/start ' + code) {
      setProp_(P_OWNER, chatId);
      deleteProp_(P_LINK_CODE);
      sendMessage_(chatId, 'Готово, бот привязан к вам. Другим людям он отвечать не будет.\n\n' + helpText_());
    } else {
      sendMessage_(chatId, 'Это личный бот, он отвечает только своему владельцу.');
    }
    return;
  }
  if (!text) return;

  const m = text.match(/^\/(\w+)(?:@\w+)?\s*([\s\S]*)$/);
  if (!m) {
    cmdFind_(chatId, text);
    return;
  }
  const args = m[2].trim();
  switch (m[1].toLowerCase()) {
    case 'start':
    case 'help':
      sendMessage_(chatId, helpText_());
      break;
    case 'today':
      cmdSoon_(chatId, '0');
      break;
    case 'soon':
      cmdSoon_(chatId, args);
      break;
    case 'list':
      cmdList_(chatId);
      break;
    case 'add':
      cmdAdd_(chatId, args);
      break;
    case 'edit':
      cmdEdit_(chatId, args);
      break;
    case 'delete':
    case 'del':
      cmdDelete_(chatId, args);
      break;
    default:
      sendMessage_(chatId, 'Не знаю такой команды. /help — список команд.');
  }
}

/** One line for lists: "#5 Иван Петров — 12.03, через 3 дня (36 лет)". */
function personLine_(p, today) {
  let line = '#' + p.id + ' ' + esc_(p.name) + ' — ';
  if (!p.birthday) return line + '⚠️ не понял дату «' + esc_(p.dateText) + '»';
  const next = nextOccurrence_(p.birthday, today);
  line += formatBirthday_(p.birthday).slice(0, 5) + ', ' + whenText_(next.daysLeft);
  if (next.age !== null) line += ' (' + yearsText_(next.age) + ')';
  return line;
}

function personCard_(p, today) {
  const lines = ['<b>' + esc_(p.name) + '</b> (#' + p.id + ')'];
  if (p.birthday) {
    const next = nextOccurrence_(p.birthday, today);
    let when = '🎂 ' + formatBirthday_(p.birthday) + ' — ' + whenText_(next.daysLeft);
    if (next.age !== null) when += ', исполнится ' + yearsText_(next.age);
    lines.push(when);
  } else {
    lines.push('⚠️ Не понял дату «' + esc_(p.dateText) + '». Исправьте: /edit ' + p.id + ' дата ДД.ММ.ГГГГ');
  }
  if (p.group) lines.push('👥 ' + esc_(p.group));
  if (p.note) lines.push('📝 ' + esc_(p.note));
  return lines.join('\n');
}

function personButtons_(p) {
  return {
    inline_keyboard: [[
      { text: '✏️ Изменить', callback_data: 'edit:' + p.id },
      { text: '🗑 Удалить', callback_data: 'del:' + p.id },
    ]],
  };
}

function sortedByNext_(people, today) {
  return people
    .filter(function (p) { return p.birthday; })
    .map(function (p) { return { p: p, next: nextOccurrence_(p.birthday, today) }; })
    .sort(function (a, b) { return a.next.daysLeft - b.next.daysLeft || a.p.name.localeCompare(b.p.name); });
}

function cmdList_(chatId) {
  const people = readPeople_();
  if (!people.length) {
    sendMessage_(chatId, 'Список пуст. Добавьте человека:\n<code>/add Иван Петров; 12.03.1990; коллега</code>');
    return;
  }
  const today = today_();
  const lines = ['<b>Все (' + people.length + ')</b>'];
  sortedByNext_(people, today).forEach(function (x) { lines.push(personLine_(x.p, today)); });
  people.filter(function (p) { return !p.birthday; }).forEach(function (p) { lines.push(personLine_(p, today)); });
  sendLong_(chatId, lines.join('\n'));
}

function cmdSoon_(chatId, args) {
  const days = args ? parseInt(args, 10) : SOON_DAYS_DEFAULT;
  if (isNaN(days) || days < 0 || days > 366) {
    sendMessage_(chatId, 'Укажите число дней от 0 до 366, например: /soon 60');
    return;
  }
  const today = today_();
  const items = sortedByNext_(readPeople_(), today).filter(function (x) { return x.next.daysLeft <= days; });
  if (!items.length) {
    sendMessage_(chatId, days === 0 ? 'Сегодня дней рождения нет.' : 'В ближайшие ' + days + ' ' + plural_(days, 'день', 'дня', 'дней') + ' дней рождения нет.');
    return;
  }
  const title = days === 0 ? '<b>Сегодня</b>' : '<b>Ближайшие ' + days + ' ' + plural_(days, 'день', 'дня', 'дней') + '</b>';
  sendLong_(chatId, [title].concat(items.map(function (x) { return personLine_(x.p, today); })).join('\n'));
}

function cmdFind_(chatId, query) {
  const q = query.toLowerCase();
  const found = readPeople_().filter(function (p) {
    return p.name.toLowerCase().indexOf(q) >= 0 || p.group.toLowerCase().indexOf(q) >= 0 || String(p.id) === q.replace(/^#/, '');
  });
  if (!found.length) {
    sendMessage_(chatId, 'Никого не нашёл по «' + esc_(query) + '». /help — список команд.');
    return;
  }
  if (found.length > 10) {
    sendMessage_(chatId, 'Нашлось ' + found.length + ' человек, уточните запрос. Первые 10 — ниже.');
  }
  const today = today_();
  found.slice(0, 10).forEach(function (p) { sendMessage_(chatId, personCard_(p, today), personButtons_(p)); });
}

function cmdAdd_(chatId, args) {
  const parts = args.split(/\s*[;\n]\s*/);
  const name = (parts[0] || '').trim();
  const dateText = (parts[1] || '').trim();
  if (!name || !dateText) {
    sendMessage_(chatId, 'Формат: <code>/add Имя Фамилия; ДД.ММ.ГГГГ; кто; заметка</code>\nНапример: <code>/add Иван Петров; 12.03.1990; коллега</code>');
    return;
  }
  const birthday = parseBirthday_(dateText, today_().year);
  if (!birthday) {
    sendMessage_(chatId, 'Не понял дату «' + esc_(dateText) + '». Пишите ДД.ММ.ГГГГ или ДД.ММ, например 12.03.1990.');
    return;
  }
  const id = addPerson_({
    name: name,
    dateText: formatBirthday_(birthday),
    group: (parts[2] || '').trim(),
    note: parts.slice(3).join('; ').trim(),
  });
  sendMessage_(chatId, 'Добавил:\n\n' + personCard_(findPerson_(id), today_()));
}

function cmdEdit_(chatId, args) {
  const m = args.match(/^#?(\d+)\s+(\S+)\s*([\s\S]*)$/);
  const field = m ? EDIT_FIELDS[m[2].toLowerCase()] : null;
  if (!m || !field) {
    sendMessage_(chatId, 'Формат: <code>/edit номер поле значение</code>\nПоля: имя, дата, кто, заметка. Например: <code>/edit 5 дата 12.03.1990</code>');
    return;
  }
  const id = Number(m[1]);
  let value = m[3].trim();
  if (field === 'name' && !value) {
    sendMessage_(chatId, 'Имя не может быть пустым.');
    return;
  }
  if (field === 'date') {
    const birthday = parseBirthday_(value, today_().year);
    if (!birthday) {
      sendMessage_(chatId, 'Не понял дату «' + esc_(value) + '». Пишите ДД.ММ.ГГГГ или ДД.ММ.');
      return;
    }
    value = formatBirthday_(birthday);
  }
  if (!updatePerson_(id, field, value)) {
    sendMessage_(chatId, 'Нет человека с номером ' + id + '. Номера — в /list.');
    return;
  }
  sendMessage_(chatId, 'Сохранил:\n\n' + personCard_(findPerson_(id), today_()));
}

function cmdDelete_(chatId, args) {
  const id = Number(String(args).replace(/^#/, ''));
  const p = id ? findPerson_(id) : null;
  if (!p) {
    sendMessage_(chatId, 'Формат: <code>/delete номер</code>. Номера — в /list.');
    return;
  }
  sendMessage_(chatId, 'Удалить?\n\n' + personCard_(p, today_()), confirmDeleteButtons_(id));
}

function confirmDeleteButtons_(id) {
  return {
    inline_keyboard: [[
      { text: 'Да, удалить', callback_data: 'delok:' + id },
      { text: 'Отмена', callback_data: 'cancel' },
    ]],
  };
}

function handleCallback_(cb) {
  const chatId = cb.message && cb.message.chat.id;
  if (!isOwner_(chatId)) {
    answerCallback_(cb.id, 'Это личный бот.');
    return;
  }
  const messageId = cb.message.message_id;
  const parts = String(cb.data || '').split(':');
  const id = Number(parts[1]);

  if (parts[0] === 'edit') {
    answerCallback_(cb.id);
    sendMessage_(chatId, [
      'Скопируйте нужную строку, поправьте значение и отправьте:',
      '<code>/edit ' + id + ' имя </code>',
      '<code>/edit ' + id + ' дата </code>',
      '<code>/edit ' + id + ' кто </code>',
      '<code>/edit ' + id + ' заметка </code>',
    ].join('\n'));
  } else if (parts[0] === 'del') {
    answerCallback_(cb.id);
    const p = findPerson_(id);
    if (p) sendMessage_(chatId, 'Удалить?\n\n' + personCard_(p, today_()), confirmDeleteButtons_(id));
    else sendMessage_(chatId, 'Этого человека уже нет в списке.');
  } else if (parts[0] === 'delok') {
    const p = deletePerson_(id);
    answerCallback_(cb.id, p ? 'Удалено' : 'Уже удалено');
    editMessage_(chatId, messageId, p ? '🗑 Удалил: ' + esc_(p.name) : 'Этого человека уже нет в списке.');
  } else if (parts[0] === 'cancel') {
    answerCallback_(cb.id, 'Отменено');
    editMessage_(chatId, messageId, 'Ничего не удалял.');
  } else {
    answerCallback_(cb.id);
  }
}

// ===== Config.js =====

/**
 * Settings. Secrets (bot token, owner chat id) live in Script Properties,
 * never in code: Project Settings → Script Properties.
 */
const TZ = 'Europe/Moscow';
const REMIND_HOUR = 10;
const SOON_DAYS_DEFAULT = 30;

const SHEET_NAME = 'Люди';
const HEADERS = ['ID', 'Имя', 'Дата рождения', 'Кто', 'Заметка'];
const COL = { id: 1, name: 2, date: 3, group: 4, note: 5 }; // 1-based sheet columns

// Script Properties keys
const P_TOKEN = 'BOT_TOKEN';
const P_OWNER = 'OWNER_CHAT_ID';
const P_LINK_CODE = 'LINK_CODE';
const P_SPREADSHEET = 'SPREADSHEET_ID';
const P_OFFSET = 'UPDATE_OFFSET';
const P_LAST_REMINDER = 'LAST_REMINDER_DATE';

function prop_(key) {
  return PropertiesService.getScriptProperties().getProperty(key);
}

function setProp_(key, value) {
  PropertiesService.getScriptProperties().setProperty(key, String(value));
}

function deleteProp_(key) {
  PropertiesService.getScriptProperties().deleteProperty(key);
}

/** Current moment; a separate function so tests can freeze time. */
function now_() {
  return new Date();
}

// ===== Dates.js =====

/**
 * Pure date helpers: no Google services here except Utilities.formatDate in today_().
 * A birthday is {day, month, year|null}; year is optional ("12.03" is fine).
 */

function isLeap_(year) {
  return (year % 4 === 0 && year % 100 !== 0) || year % 400 === 0;
}

function daysInMonth_(month, year) {
  if (month === 2) return year === null || isLeap_(year) ? 29 : 28;
  return [4, 6, 9, 11].indexOf(month) >= 0 ? 30 : 31;
}

/** "12.03", "12.03.1990", "1/3/1990", "12-03" → birthday, or null if not a valid date. */
function parseBirthday_(text, currentYear) {
  const m = String(text || '').trim().match(/^(\d{1,2})[.\/-](\d{1,2})(?:[.\/-](\d{4}))?$/);
  if (!m) return null;
  const day = Number(m[1]);
  const month = Number(m[2]);
  const year = m[3] ? Number(m[3]) : null;
  if (month < 1 || month > 12) return null;
  if (year !== null && (year < 1900 || year > currentYear)) return null;
  if (day < 1 || day > daysInMonth_(month, year)) return null;
  return { day: day, month: month, year: year };
}

function pad2_(n) {
  return (n < 10 ? '0' : '') + n;
}

function formatBirthday_(b) {
  return pad2_(b.day) + '.' + pad2_(b.month) + (b.year ? '.' + b.year : '');
}

/** Today in Moscow as {year, month, day}. */
function today_() {
  const parts = Utilities.formatDate(now_(), TZ, 'yyyy-MM-dd').split('-').map(Number);
  return { year: parts[0], month: parts[1], day: parts[2] };
}

function todayKey_() {
  const t = today_();
  return t.year + '-' + pad2_(t.month) + '-' + pad2_(t.day);
}

/** Birthday date in a given year: 29.02 is celebrated on 28.02 in non-leap years. */
function occurrenceIn_(b, year) {
  const day = b.month === 2 && b.day === 29 && !isLeap_(year) ? 28 : b.day;
  return { year: year, month: b.month, day: day };
}

function dayNumber_(d) {
  return Math.round(Date.UTC(d.year, d.month - 1, d.day) / 86400000);
}

/** Next birthday on or after `today`: {date, daysLeft, age|null}. */
function nextOccurrence_(b, today) {
  let occ = occurrenceIn_(b, today.year);
  if (dayNumber_(occ) < dayNumber_(today)) occ = occurrenceIn_(b, today.year + 1);
  return {
    date: occ,
    daysLeft: dayNumber_(occ) - dayNumber_(today),
    age: b.year ? occ.year - b.year : null,
  };
}

/** Russian plural: plural_(5, 'год', 'года', 'лет') → 'лет'. */
function plural_(n, one, few, many) {
  const n10 = n % 10;
  const n100 = n % 100;
  if (n10 === 1 && n100 !== 11) return one;
  if (n10 >= 2 && n10 <= 4 && (n100 < 12 || n100 > 14)) return few;
  return many;
}

function yearsText_(n) {
  return n + ' ' + plural_(n, 'год', 'года', 'лет');
}

function whenText_(daysLeft) {
  if (daysLeft === 0) return 'сегодня';
  if (daysLeft === 1) return 'завтра';
  return 'через ' + daysLeft + ' ' + plural_(daysLeft, 'день', 'дня', 'дней');
}

// ===== Main.js =====

/**
 * Entry points. Run setup() once from the Apps Script editor;
 * after that a trigger calls pollUpdates() every minute: it answers messages
 * and, from 10:00 Moscow time, sends today's reminder (once a day).
 */

/** One-time setup: sheet, bot menu, triggers, link for binding the bot to you. */
function setup() {
  if (!prop_(P_TOKEN)) {
    throw new Error('Сначала добавьте BOT_TOKEN: Настройки проекта → Свойства скрипта.');
  }
  getSheet_();

  // getUpdates does not work while a webhook is set.
  tg_('deleteWebhook', { drop_pending_updates: false });
  tg_('setMyCommands', {
    commands: [
      { command: 'today', description: 'У кого сегодня день рождения' },
      { command: 'soon', description: 'Ближайшие 30 дней' },
      { command: 'list', description: 'Все, по ближайшей дате' },
      { command: 'add', description: 'Добавить: /add Имя; ДД.ММ.ГГГГ; кто; заметка' },
      { command: 'edit', description: 'Изменить: /edit номер поле значение' },
      { command: 'delete', description: 'Удалить: /delete номер' },
      { command: 'help', description: 'Справка' },
    ],
  });

  installTriggers_();

  if (prop_(P_OWNER)) {
    Logger.log('Готово. Бот уже привязан к вашему Telegram.');
    return;
  }
  const code = Utilities.getUuid().replace(/-/g, '').slice(0, 16);
  setProp_(P_LINK_CODE, code);
  const bot = tg_('getMe', {});
  Logger.log('Готово. Откройте эту ссылку в Telegram и нажмите «Старт» (в течение минуты бот ответит):\n'
    + 'https://t.me/' + bot.username + '?start=' + code);
}

function installTriggers_() {
  // A daily trigger would fire at a random minute between 10:00 and 11:00,
  // so the reminder is sent by the every-minute trigger instead.
  ScriptApp.getProjectTriggers().forEach(function (t) {
    if (t.getHandlerFunction() === 'pollUpdates') ScriptApp.deleteTrigger(t);
  });
  ScriptApp.newTrigger('pollUpdates').timeBased().everyMinutes(1).create();
}

/** Every minute: answer new messages, then send today's reminder if it is due. */
function pollUpdates() {
  const lock = LockService.getScriptLock();
  if (!lock.tryLock(1000)) return; // previous run is still working
  try {
    const offset = Number(prop_(P_OFFSET) || 0);
    const updates = tg_('getUpdates', {
      offset: offset,
      timeout: 0,
      allowed_updates: ['message', 'callback_query'],
    });
    updates.forEach(function (u) {
      // Move the offset first: a message that crashes the bot must not be retried forever.
      setProp_(P_OFFSET, u.update_id + 1);
      try {
        handleUpdate_(u);
      } catch (e) {
        console.error(e);
        notifyOwnerOfError_(e);
      }
    });
    sendReminderIfDue_();
  } finally {
    lock.releaseLock();
  }
}

/** From REMIND_HOUR Moscow time; at most once a day, retried next minute if sending failed. */
function sendReminderIfDue_() {
  const owner = prop_(P_OWNER);
  if (!owner) return;
  if (Number(Utilities.formatDate(now_(), TZ, 'H')) < REMIND_HOUR) return;
  const key = todayKey_();
  if (prop_(P_LAST_REMINDER) === key) return;

  const message = buildReminder_(readPeople_(), today_());
  if (message) sendMessage_(owner, message);
  setProp_(P_LAST_REMINDER, key);
}

/** Text of today's reminder, or null if nobody has a birthday today. */
function buildReminder_(people, today) {
  const todays = people.filter(function (p) {
    return p.birthday && nextOccurrence_(p.birthday, today).daysLeft === 0;
  });
  if (!todays.length) return null;
  const blocks = todays.map(function (p) {
    const next = nextOccurrence_(p.birthday, today);
    const lines = ['<b>' + esc_(p.name) + '</b>' + (next.age !== null ? ' — ' + yearsText_(next.age) : '')];
    if (p.group) lines.push('👥 ' + esc_(p.group));
    if (p.note) lines.push('📝 ' + esc_(p.note));
    return lines.join('\n');
  });
  const title = todays.length === 1 ? '🎉 Сегодня день рождения!' : '🎉 Сегодня дни рождения!';
  return title + '\n\n' + blocks.join('\n\n');
}

function notifyOwnerOfError_(e) {
  const owner = prop_(P_OWNER);
  if (!owner) return;
  try {
    sendMessage_(owner, '⚠️ Ошибка: ' + esc_(e && e.message ? e.message : e));
  } catch (ignored) {
    // Telegram itself is unavailable; the error is already in the execution log.
  }
}

/** Manual check from the editor: sends today's reminder regardless of the once-a-day guard. */
function testReminderNow() {
  const owner = prop_(P_OWNER);
  if (!owner) throw new Error('Бот ещё не привязан: запустите setup() и откройте ссылку из журнала.');
  const message = buildReminder_(readPeople_(), today_());
  sendMessage_(owner, message || 'Проверка: сегодня дней рождения нет, бот работает.');
}

// ===== Sheet.js =====

/**
 * The "Люди" sheet is the database: one person per row.
 * ID is assigned automatically, also for rows typed into the sheet by hand.
 */

function getSpreadsheet_() {
  const id = prop_(P_SPREADSHEET);
  return id ? SpreadsheetApp.openById(id) : SpreadsheetApp.getActiveSpreadsheet();
}

function getSheet_() {
  const ss = getSpreadsheet_();
  let sh = ss.getSheetByName(SHEET_NAME);
  if (!sh) {
    sh = ss.insertSheet(SHEET_NAME);
    sh.getRange(1, 1, 1, HEADERS.length).setValues([HEADERS]).setFontWeight('bold');
    sh.setFrozenRows(1);
  }
  // Plain text, otherwise Sheets turns "12.03" into a date with the current year.
  sh.getRange(1, COL.date, sh.getMaxRows(), 1).setNumberFormat('@');
  return sh;
}

/** Cell value of the date column as text "dd.MM[.yyyy]". */
function dateCellText_(value, sheetTz, currentYear) {
  if (Object.prototype.toString.call(value) === '[object Date]') {
    if (isNaN(value.getTime())) return '';
    const text = Utilities.formatDate(value, sheetTz, 'dd.MM.yyyy');
    // A date typed without a year was stored with the current one: drop it.
    return Number(text.slice(6)) >= currentYear ? text.slice(0, 5) : text;
  }
  return String(value === null || value === undefined ? '' : value).trim();
}

/** All people: [{row, id, name, dateText, birthday|null, group, note}]. */
function readPeople_() {
  const sh = getSheet_();
  const last = sh.getLastRow();
  if (last < 2) return [];
  const sheetTz = getSpreadsheet_().getSpreadsheetTimeZone();
  const currentYear = today_().year;
  const values = sh.getRange(2, 1, last - 1, HEADERS.length).getValues();

  const people = [];
  values.forEach(function (r, i) {
    const name = String(r[COL.name - 1]).trim();
    const dateText = dateCellText_(r[COL.date - 1], sheetTz, currentYear);
    if (!name && !dateText) return;
    people.push({
      row: i + 2,
      id: Number(r[COL.id - 1]) || null,
      name: name,
      dateText: dateText,
      birthday: parseBirthday_(dateText, currentYear),
      group: String(r[COL.group - 1]).trim(),
      note: String(r[COL.note - 1]).trim(),
    });
  });

  let maxId = people.reduce(function (m, p) { return Math.max(m, p.id || 0); }, 0);
  people.forEach(function (p) {
    if (!p.id) {
      p.id = ++maxId;
      sh.getRange(p.row, COL.id).setValue(p.id);
    }
  });
  return people;
}

function findPerson_(id) {
  return readPeople_().filter(function (p) { return p.id === id; })[0] || null;
}

function addPerson_(person) {
  const sh = getSheet_();
  const people = readPeople_();
  const id = people.reduce(function (m, p) { return Math.max(m, p.id); }, 0) + 1;
  const row = sh.getLastRow() + 1;
  sh.getRange(row, 1, 1, HEADERS.length).setValues([
    [id, person.name, person.dateText, person.group || '', person.note || ''],
  ]);
  return id;
}

/** field: one of 'name' | 'date' | 'group' | 'note'. */
function updatePerson_(id, field, value) {
  const p = findPerson_(id);
  if (!p) return false;
  getSheet_().getRange(p.row, COL[field]).setValue(value);
  return true;
}

function deletePerson_(id) {
  const p = findPerson_(id);
  if (!p) return null;
  getSheet_().deleteRow(p.row);
  return p;
}

// ===== Telegram.js =====

/** Minimal Telegram Bot API client. */

const TG_MAX_TEXT = 4000; // Telegram limit is 4096

function tg_(method, payload) {
  const token = prop_(P_TOKEN);
  if (!token) throw new Error('Не задан BOT_TOKEN в свойствах скрипта');
  const resp = UrlFetchApp.fetch('https://api.telegram.org/bot' + token + '/' + method, {
    method: 'post',
    contentType: 'application/json',
    payload: JSON.stringify(payload || {}),
    muteHttpExceptions: true,
  });
  const body = JSON.parse(resp.getContentText());
  if (!body.ok) throw new Error('Telegram ' + method + ': ' + body.description);
  return body.result;
}

function sendMessage_(chatId, text, replyMarkup) {
  const payload = {
    chat_id: chatId,
    text: text,
    parse_mode: 'HTML',
    disable_web_page_preview: true,
  };
  if (replyMarkup) payload.reply_markup = replyMarkup;
  return tg_('sendMessage', payload);
}

/** Sends a long text as several messages, splitting on line breaks. */
function sendLong_(chatId, text) {
  let chunk = '';
  text.split('\n').forEach(function (line) {
    if (chunk && chunk.length + line.length + 1 > TG_MAX_TEXT) {
      sendMessage_(chatId, chunk);
      chunk = '';
    }
    chunk += (chunk ? '\n' : '') + line;
  });
  if (chunk) sendMessage_(chatId, chunk);
}

function editMessage_(chatId, messageId, text) {
  return tg_('editMessageText', {
    chat_id: chatId,
    message_id: messageId,
    text: text,
    parse_mode: 'HTML',
  });
}

function answerCallback_(callbackId, text) {
  return tg_('answerCallbackQuery', { callback_query_id: callbackId, text: text || '' });
}

function esc_(s) {
  return String(s).replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;');
}
