/**
 * Settings. The bot token is taken from Script Properties (BOT_TOKEN) or, if it is
 * not set there, from BOT_TOKEN_IN_CODE. Keep BOT_TOKEN_IN_CODE empty in git.
 */
const BOT_TOKEN_IN_CODE = '';

const TZ = 'Europe/Moscow';
const REMIND_HOUR = 10;
const SOON_DAYS_DEFAULT = 30;

const SHEET_NAME = 'Люди';
// Column order matches the list as it is kept today: № | ФИО | Должность | День рождения | Компания.
// Header texts may differ ("TASK" instead of "ФИО" is fine): columns are read by position.
const HEADERS = ['№', 'ФИО', 'Должность', 'День рождения', 'Компания'];
const COL = { id: 1, name: 2, position: 3, date: 4, company: 5 }; // 1-based sheet columns

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

function botToken_() {
  return prop_(P_TOKEN) || BOT_TOKEN_IN_CODE;
}

/** Current moment; a separate function so tests can freeze time. */
function now_() {
  return new Date();
}
