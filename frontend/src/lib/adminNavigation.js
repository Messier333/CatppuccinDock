const groups = [
  { id: 'bookmarks', name: '내 북마크', sections: ['bookmarks'] },
  { id: 'links', name: '공개 링크', sections: ['library', 'shared'] },
  { id: 'preferences', name: '개인 설정 · 앱 설치', sections: ['preferences'] },
  { id: 'settings', name: '포털 설정', sections: ['settings'] },
  { id: 'backgrounds', name: 'GIF · 배경 관리', sections: ['backgrounds'] },
  { id: 'accounts', name: '계정 · 보안', sections: ['security', 'sso'] },
  { id: 'users', name: '사용자 · 그룹', sections: ['users', 'groups'] },
  { id: 'integrations', name: '서비스 연동', sections: ['proxmox', 'import', 'sync'] },
  { id: 'monitoring', name: '서비스 상태', sections: ['monitoring'] },
  { id: 'footer', name: '하단바 · 모니터링', sections: ['footer'] },
  { id: 'backup', name: '백업 · 가져오기', sections: ['backup'] },
  { id: 'trash', name: '휴지통', sections: ['trash'] },
];

// Keep saved section IDs and their relative order. The API still validates the
// complete, role-specific section list when a user reorders the grouped menu.
export function groupSettingsSections(sections) {
  const positions = new Map(sections.map((section, index) => [section.id, index]));
  const grouped = groups.map(group => ({
    ...group,
    sections: sections.filter(section => group.sections.includes(section.id)),
  })).filter(group => group.sections.length);
  const known = new Set(groups.flatMap(group => group.sections));
  for (const section of sections) {
    if (!known.has(section.id)) grouped.push({ id: section.id, name: section.name, sections: [section] });
  }
  return grouped.sort((a, b) => positions.get(a.sections[0].id) - positions.get(b.sections[0].id));
}

export function sectionOrderForGroups(groups, order) {
  const byId = new Map(groups.map(group => [group.id, group]));
  if (order.length !== byId.size || new Set(order).size !== byId.size || order.some(id => !byId.has(id))) {
    throw new Error('설정 메뉴 구성이 변경됐습니다. 새로 불러온 뒤 순서를 변경하세요.');
  }
  return order.flatMap(id => byId.get(id).sections.map(section => section.id));
}
