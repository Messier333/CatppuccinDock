import test from 'node:test';
import assert from 'node:assert/strict';
import { formatClock, formatDate } from '../src/lib/clock.js';

test('clock uses selected timezone and explicit AM/PM or 24-hour format', () => {
  const date = new Date('2026-10-20T09:30:00Z');
  assert.equal(formatClock(date, { timezone: 'Asia/Seoul', format: '24h' }), '18:30');
  assert.equal(formatClock(date, { timezone: 'Asia/Seoul', format: '12h' }), '06:30 PM');
  assert.equal(formatClock(date, { timezone: 'America/New_York', format: '12h' }), '05:30 AM');
});
test('midnight is 00 in 24-hour mode and date follows the same timezone', () => {
  const date = new Date('2026-10-20T15:05:00Z');
  assert.equal(formatClock(date, { timezone: 'Asia/Seoul', format: '24h' }), '00:05');
  assert.equal(formatClock(date, { timezone: 'Asia/Seoul', format: '12h' }), '12:05 AM');
  assert.match(formatDate(date, { timezone: 'Asia/Seoul' }), /21일/);
  assert.match(formatDate(date, { timezone: 'UTC' }), /20일/);
});
