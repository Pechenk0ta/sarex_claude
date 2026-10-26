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
