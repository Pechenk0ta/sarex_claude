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

/** "12.03", "12.03.1990", "1/3/1990", "12-03" → birthday, or null if not a valid date. "dd.MM.1900" = year unknown. */
function parseBirthday_(text, currentYear) {
  const m = String(text || '').trim().match(/^(\d{1,2})[.\/-](\d{1,2})(?:[.\/-](\d{4}))?$/);
  if (!m) return null;
  const day = Number(m[1]);
  const month = Number(m[2]);
  let year = m[3] ? Number(m[3]) : null;
  if (year === UNKNOWN_YEAR) year = null;
  if (month < 1 || month > 12) return null;
  if (year !== null && (year < UNKNOWN_YEAR || year > currentYear)) return null;
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
