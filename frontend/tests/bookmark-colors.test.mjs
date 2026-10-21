import test from 'node:test';
import assert from 'node:assert/strict';
import { bookmarkColor } from '../src/lib/bookmarkColors.js';
import { findBookmarks } from '../src/lib/search.js';

test('automatic colors repeat per category and manual colors override their slot', () => {
  const links = [{ icon_color: 'auto' }, { icon_color: '#123456' }, {}, {}, {}, {}];
  assert.deepEqual(links.map(bookmarkColor), ['var(--green)', '#123456', 'var(--red)', 'var(--blue)', 'var(--mauve)', 'var(--green)']);
  assert.equal(bookmarkColor({}, -1), 'var(--green)');
  assert.equal(bookmarkColor({}, 6), 'var(--peach)');
});
test('automatic colors follow reorder while explicit colors remain fixed', () => {
  const automatic = { icon_color: 'auto' }, manual = { icon_color: '#abcdef' };
  assert.deepEqual([automatic, manual].map(bookmarkColor), ['var(--green)', '#abcdef']);
  assert.deepEqual([manual, automatic].map(bookmarkColor), ['#abcdef', 'var(--peach)']);
});
test('search retains original category color after filtering and ranking', () => {
  const tabs = [{ name: 'Home', categories: [
    { name: 'Tools', links: [{ id: '1', name: 'First', url: 'https://first.test', icon_color: 'auto' }, { id: '2', name: 'Docker', url: 'https://docker.test', icon_color: 'auto' }] },
    { name: 'Other', links: [{ id: '3', name: 'Docker docs', url: 'https://docs.test', icon_color: 'auto' }] },
  ] }];
  assert.deepEqual(findBookmarks(tabs, 'docker').map(link => [link.id, link.displayColor]), [['2','var(--peach)'], ['3','var(--green)']]);
});
