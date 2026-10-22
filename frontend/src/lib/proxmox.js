export const metricLabels = { guests: '가동 게스트', nodes: '온라인 노드', cpu: 'CPU', memory: '메모리', storage: '스토리지' };
export const sectionLabels = { overview: '요약', nodes: '노드', guests: 'VM · 컨테이너', storage: '스토리지', tasks: '작업 내역' };
export const columnLabels = { status: '상태', node: '노드', cpu: 'CPU', memory: '메모리', disk: '디스크', uptime: '가동 시간' };
export const actionLabels = { start: '시작', shutdown: '정상 종료', reboot: '재부팅', stop: '강제 중지', reset: '강제 재시작', suspend: '일시 중지', resume: '다시 시작', snapshot: '스냅샷 생성', snapshot_delete: '스냅샷 삭제', rollback: '스냅샷 복원', backup: '백업 실행', clone: '전체 복제', migrate: '노드 이동', cpu: 'CPU 코어 변경', memory: '메모리 변경', onboot: '자동 시작 변경', template: '템플릿 변환', delete: 'VM·컨테이너 삭제', node_reboot: '노드 재부팅', node_shutdown: '노드 종료' };
export function presentation(config) {
  return Object.fromEntries(['bookmark_ids', 'metrics', 'sections', 'columns'].map(key => [key, JSON.parse(JSON.stringify(config[key]))]));
}
export function defaults() {
  return { name: '', base_url: '', token_id: '', token: '', ca_certificate: '', allow_private: true, enabled: true, controls: false, interval: 60, nodes: [], bookmark_ids: [], metrics: ['guests'], sections: Object.keys(sectionLabels).map(id => ({ id, visible: true, width: 'full' })), columns: ['status', 'node', 'cpu', 'memory'] };
}
export function metricText(summary, key) {
  const value = summary?.[key];
  if (value == null) return '—';
  if (typeof value === 'object') return `${value.value}/${value.total} ${key === 'guests' ? '가동' : '온라인'}`;
  return `${metricLabels[key]} ${value}%`;
}
export function bytes(value) {
  if (!Number.isFinite(value)) return '—';
  if (value < 1024 ** 3) return `${(value / 1024 ** 2).toFixed(0)} MiB`;
  return `${(value / 1024 ** 3).toFixed(1)} GiB`;
}
export function cell(row, key) {
  if (key === 'status') return ({ running: '가동', stopped: '중지', online: '온라인', offline: '오프라인' })[row.status] || row.status;
  if (key === 'cpu') return `${(row.cpu * 100).toFixed(1)}%`;
  if (key === 'memory') return `${bytes(row.mem)} / ${bytes(row.maxmem)}`;
  if (key === 'disk') return `${bytes(row.disk)} / ${bytes(row.maxdisk)}`;
  if (key === 'uptime') return `${Math.floor(row.uptime / 86400)}일 ${Math.floor(row.uptime % 86400 / 3600)}시간`;
  return row[key];
}
