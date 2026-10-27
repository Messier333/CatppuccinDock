import test from 'node:test';
import assert from 'node:assert/strict';
import { groupSettingsSections, sectionOrderForGroups } from '../src/lib/adminNavigation.js';

const member = ['bookmarks', 'preferences', 'library', 'backup', 'trash', 'security', 'proxmox'].map(id => ({id,name:id}));
const admin = [...member, ...['backgrounds','groups','footer','monitoring','sync','users','import','shared','settings','sso'].map(id=>({id,name:id}))];

test('grouping reduces menus while preserving each accessible section exactly once', () => {
  for (const [sections,count] of [[member,7],[admin,12]]) {
    const grouped=groupSettingsSections(sections);
    assert.equal(grouped.length,count);
    assert.deepEqual(grouped.flatMap(group=>group.sections.map(section=>section.id)).sort(),sections.map(section=>section.id).sort());
  }
  const account=groupSettingsSections(admin).find(group=>group.id==='accounts');
  assert.ok(account.sections.some(section=>section.id==='sso'));
  assert.ok(!groupSettingsSections(member).flatMap(group=>group.sections).some(section=>['sso','users','settings','import'].includes(section.id)));
});
test('saved section order determines group priority and survives grouped reordering', () => {
  const previous=[...admin].reverse();
  const grouped=groupSettingsSections(previous);
  assert.equal(grouped[0].id,'accounts');
  const order=grouped.map(group=>group.id).reverse();
  const flattened=sectionOrderForGroups(grouped,order);
  const restored=groupSettingsSections(flattened.map(id=>previous.find(section=>section.id===id)));
  assert.deepEqual(restored.map(group=>group.id),order);
  for(const group of grouped)assert.deepEqual(restored.find(item=>item.id===group.id).sections,group.sections);
});
test('new sections remain visible and incomplete or foreign group orders are rejected', () => {
  const grouped=groupSettingsSections([...member,{id:'future',name:'Future settings'}]);
  assert.ok(grouped.some(group=>group.sections.some(section=>section.id==='future')));
  const ids=grouped.map(group=>group.id);
  for(const invalid of [ids.slice(1),[...ids,ids[0]],ids.map((id,index)=>index===0?'foreign':id)]) {
    assert.throws(()=>sectionOrderForGroups(grouped,invalid));
  }
});
