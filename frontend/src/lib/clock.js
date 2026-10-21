export function formatClock(date, clock = {}) {
  const hour12 = clock.format === '12h';
  return new Intl.DateTimeFormat(hour12 ? 'en-US' : 'en-GB', {
    hour: '2-digit', minute: '2-digit', hourCycle: hour12 ? 'h12' : 'h23',
    timeZone: clock.timezone || 'Asia/Seoul',
  }).format(date);
}

export function formatDate(date, clock = {}) {
  return new Intl.DateTimeFormat('ko-KR', {
    weekday: 'long', year: 'numeric', month: 'long', day: 'numeric',
    timeZone: clock.timezone || 'Asia/Seoul',
  }).format(date);
}
