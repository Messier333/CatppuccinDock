import test from 'node:test';
import assert from 'node:assert/strict';
import { searchSettings } from '../src/lib/settingsSearch.js';

const member = [{ id:'bookmarks', name:'내 북마크' }, { id:'security', name:'계정 · 보안' }, {id:'preferences',name:'개인 설정 · 앱 설치'}];
const admin = [...member, { id:'settings', name:'포털 공통 설정' }, { id:'footer', name:'하단바 · 모니터링' }, {id:'sso',name:'SSO · 로그인'}];
test('feature names and aliases find the matching settings destination', () => {
  assert.equal(searchSettings(admin, '슬라이딩')[0].anchor, 'personal-animation');
  assert.equal(searchSettings(admin, '슬라이딩')[0].section, 'preferences');
  assert.equal(searchSettings(admin, '  Ｇｒａｆａｎａ  ')[0].anchor, 'footer-widgets');
  assert.equal(searchSettings(admin, '2FA')[0].section, 'security');
  assert.equal(searchSettings(member, '기기관리')[0].anchor, 'sessions');
  assert.equal(searchSettings(admin, '하단바 순서')[0].anchor, 'footer-layout');
  assert.equal(searchSettings(admin, '검색 새창')[0].anchor, 'search-window');
  assert.equal(searchSettings(admin, 'SSO')[0].section, 'sso');
});
test('search is limited to accessible sections and requires every query term', () => {
  assert.deepEqual(searchSettings(member, 'SSO'), []);
  assert.equal(searchSettings(member, '슬라이딩')[0].anchor, 'personal-animation');
  assert.ok(searchSettings(admin, '슬라이딩').every(item => item.section === 'preferences'));
  assert.deepEqual(searchSettings(admin, 'Grafana 비밀번호'), []);
  assert.deepEqual(searchSettings(admin, '   '), []);
});
