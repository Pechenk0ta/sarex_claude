/**
 * Entry points. Run setup() once from the Apps Script editor;
 * after that a trigger calls pollUpdates() every minute: it answers messages
 * and, from 10:00 Moscow time, sends today's reminder (once a day).
 */

/** One-time setup: sheet, bot menu, triggers, link for binding the bot to you. */
function setup() {
  if (!botToken_()) {
    throw new Error('Не задан токен бота: впишите его в BOT_TOKEN_IN_CODE или в свойство скрипта BOT_TOKEN.');
  }
  getSheet_();

  // getUpdates does not work while a webhook is set.
  tg_('deleteWebhook', { drop_pending_updates: false });
  tg_('setMyCommands', {
    commands: [
      { command: 'today', description: 'У кого сегодня день рождения' },
      { command: 'soon', description: 'Ближайшие 30 дней' },
      { command: 'list', description: 'Все, по ближайшей дате' },
      { command: 'add', description: 'Добавить: /add ФИО; должность; ДД.ММ.ГГГГ; компания' },
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
    const work = workText_(p);
    if (work) lines.push('💼 ' + esc_(work));
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
