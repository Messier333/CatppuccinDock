import assert from 'node:assert/strict';
import test from 'node:test';
import { calendarDate, monthDays } from '../src/lib/calendar.js';
test('calendar follows the configured time zone across midnight', () => {
  const instant = new Date('2026-12-31T16:00:00Z');
  assert.deepEqual(calendarDate(instant, 'Asia/Seoul'), { year: 2027, month: 1, day: 1 });
  assert.deepEqual(calendarDate(instant, 'America/New_York'), { year: 2026, month: 12, day: 31 });
});
test('calendar includes leap day and full Sunday-first weeks', () => {
  const days = monthDays(2024, 2);
  assert.equal(days.length, 42);
  assert.equal(days[0].key, '2024-01-28');
  assert.equal(days.filter(day => day.month === 2).length, 29);
  assert.ok(days.some(day => day.key === '2024-02-29'));
  assert.equal(new Set(days.map(day => day.key)).size, 42);
});
test('calendar cells span year boundaries without duplicate dates', () => {
  assert.equal(monthDays(2027, 1)[0].key, '2026-12-27');
  assert.ok(monthDays(2026, 12).some(day => day.year === 2027 && day.month === 1));
});
