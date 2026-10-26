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
