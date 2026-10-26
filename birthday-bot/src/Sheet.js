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
