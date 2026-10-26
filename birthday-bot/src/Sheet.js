/**
 * The people sheet is the database: one person per row, columns as in HEADERS.
 * The number (№) is assigned automatically, also for rows typed into the sheet by hand.
 */

function getSpreadsheet_() {
  const id = prop_(P_SPREADSHEET);
  return id ? SpreadsheetApp.openById(id) : SpreadsheetApp.getActiveSpreadsheet();
}

/** Sheet named SHEET_NAME if there is one, otherwise the first sheet of the spreadsheet. */
function getSheet_() {
  const ss = getSpreadsheet_();
  const sh = ss.getSheetByName(SHEET_NAME) || ss.getSheets()[0];
  if (sh.getLastRow() === 0) {
    sh.getRange(1, 1, 1, HEADERS.length).setValues([HEADERS]).setFontWeight('bold');
    sh.setFrozenRows(1);
  }
  return sh;
}

/** Cell value of the date column as text "dd.MM[.yyyy]". */
function dateCellText_(value, sheetTz, currentYear) {
  let date = null;
  if (Object.prototype.toString.call(value) === '[object Date]') {
    date = value;
  } else if (typeof value === 'number' && value > 0) {
    // Date serial number (a date cell later formatted as a number or text).
    date = new Date(Date.UTC(1899, 11, 30) + Math.round(value) * 86400000);
    sheetTz = 'UTC';
  }
  if (date) {
    if (isNaN(date.getTime())) return '';
    const text = Utilities.formatDate(date, sheetTz, 'dd.MM.yyyy');
    // A date typed without a year was stored with the current one: drop it.
    return Number(text.slice(6)) >= currentYear ? text.slice(0, 5) : text;
  }
  return String(value === null || value === undefined ? '' : value).trim();
}

/** All people: [{row, id, name, position, dateText, birthday|null, company}]. */
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
      position: String(r[COL.position - 1]).trim(),
      dateText: dateText,
      birthday: parseBirthday_(dateText, currentYear),
      company: String(r[COL.company - 1]).trim(),
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
  const values = [];
  values[COL.id - 1] = id;
  values[COL.name - 1] = person.name;
  values[COL.position - 1] = person.position || '';
  values[COL.date - 1] = person.dateText;
  values[COL.company - 1] = person.company || '';
  // Plain text, otherwise Sheets turns "12.03" into a date with the current year.
  sh.getRange(row, COL.date).setNumberFormat('@');
  sh.getRange(row, 1, 1, HEADERS.length).setValues([values]);
  return id;
}

/** field: one of 'name' | 'position' | 'date' | 'company'. */
function updatePerson_(id, field, value) {
  const p = findPerson_(id);
  if (!p) return false;
  const cell = getSheet_().getRange(p.row, COL[field]);
  if (field === 'date') cell.setNumberFormat('@');
  cell.setValue(value);
  return true;
}

function deletePerson_(id) {
  const p = findPerson_(id);
  if (!p) return null;
  getSheet_().deleteRow(p.row);
  return p;
}
