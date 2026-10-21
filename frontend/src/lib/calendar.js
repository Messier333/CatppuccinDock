export function calendarDate(date, timezone = 'Asia/Seoul') {
  const parts = new Intl.DateTimeFormat('en-US', { timeZone: timezone, year: 'numeric', month: 'numeric', day: 'numeric' }).formatToParts(date);
  const read = key => Number(parts.find(part => part.type === key).value);
  return { year: read('year'), month: read('month'), day: read('day') };
}
export function monthDays(year, month) {
  const first = new Date(Date.UTC(year, month - 1, 1));
  return Array.from({ length: 42 }, (_, index) => {
    const date = new Date(Date.UTC(year, month - 1, 1 - first.getUTCDay() + index));
    return { year: date.getUTCFullYear(), month: date.getUTCMonth() + 1, day: date.getUTCDate(), key: date.toISOString().slice(0, 10) };
  });
}
