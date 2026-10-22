"""Private Proxmox inventories, cached per connection rather than per bookmark."""
import math
import time
from threading import BoundedSemaphore
from sqlalchemy import select

from app.db.models import ServiceIntegration
from app.db.session import SessionLocal
from app.services.proxmox.client import Client, ProxmoxError, permissions, segment

check_slots = BoundedSemaphore(4)


def number(value):
    if isinstance(value, bool):
        return 0
    try:
        result = float(value)
        return max(0, result) if math.isfinite(result) else 0
    except (ValueError, TypeError, OverflowError):
        return 0


def inventory(client, config):
    raw = client.request('GET', '/cluster/resources')
    if not isinstance(raw, list) or len(raw) > 20000:
        raise ProxmoxError('Proxmox 리소스 응답 형식을 확인하세요.')
    result = {'nodes': [], 'guests': [], 'storage': []}
    for source in raw:
        if not isinstance(source, dict) or source.get('type') not in ('node', 'qemu', 'lxc', 'storage'):
            continue
        node = segment(source.get('node', ''))
        if config.get('nodes') and node not in config['nodes']:
            continue
        kind = source['type']
        row = {key: number(source.get(key)) for key in ('cpu', 'maxcpu', 'mem', 'maxmem', 'disk', 'maxdisk', 'uptime')}
        row |= {'node': node, 'type': kind, 'status': str(source.get('status', 'unknown'))[:32], 'name': str(source.get('name') or node)[:120]}
        if kind in ('qemu', 'lxc'):
            vmid = int(number(source.get('vmid')))
            if not 100 <= vmid <= 999999999:
                continue
            row |= {'id': f'{kind}/{vmid}', 'vmid': vmid, 'template': bool(source.get('template')), 'lock': str(source.get('lock', ''))[:80]}
            result['guests'].append(row)
        elif kind == 'node':
            row['id'] = 'node/' + node
            result['nodes'].append(row)
        else:
            storage = segment(source.get('storage', ''))
            row |= {'id': 'storage/' + node + '/' + storage, 'storage': storage}
            result['storage'].append(row)
    for key in result:
        result[key].sort(key=lambda row: (row['node'], row.get('vmid', 0), row['id']))
    return result


def summary(result):
    nodes, guests, storage = (result.get(key, []) for key in ('nodes', 'guests', 'storage'))
    def percent(rows, used, total):
        maximum = sum(row[total] for row in rows)
        return round(min(100, sum(row[used] for row in rows) / maximum * 100), 1) if maximum else None
    online = [row for row in nodes if row['status'] == 'online']
    cpus = sum(row['maxcpu'] for row in online)
    return {'guests': {'value': sum(row['status'] == 'running' for row in guests), 'total': len(guests)},
            'nodes': {'value': len(online), 'total': len(nodes)},
            'cpu': round(min(100, sum(row['cpu'] * row['maxcpu'] for row in online) / cpus * 100), 1) if cpus else None,
            'memory': percent(online, 'mem', 'maxmem'), 'storage': percent(storage, 'disk', 'maxdisk')}


def refresh(integration_id, user_id):
    """A DB lease coalesces requests from tabs/workers. No perpetual cluster poll."""
    with SessionLocal.begin() as db:
        row = db.scalar(select(ServiceIntegration).where(ServiceIntegration.id == integration_id, ServiceIntegration.user_id == user_id).with_for_update())
        if not row:
            raise ProxmoxError('연동을 찾을 수 없습니다.', 404)
        now = time.time()
        if not row.config['enabled'] or row.checking_until > now or row.next_check > now:
            return
        config, encrypted, revision = dict(row.config), row.token_encrypted, row.revision
        lease = now + 45
        row.checking_until = lease
        row.next_check = now + config['interval']
    result, error = None, ''
    acquired = check_slots.acquire(blocking=False)
    try:
        if not acquired:
            raise ProxmoxError('다른 연동을 확인 중입니다. 잠시 후 다시 시도하세요.')
        client = Client(config, encrypted)
        result = inventory(client, config)
        result['_permissions'] = permissions(client)
        result['summary'] = summary(result)
    except (ProxmoxError, ValueError, TypeError) as failure:
        error = failure.public_message if isinstance(failure, ProxmoxError) else 'Proxmox 응답 형식을 확인하세요.'
    finally:
        if acquired:
            check_slots.release()
    with SessionLocal.begin() as db:
        row = db.scalar(select(ServiceIntegration).where(ServiceIntegration.id == integration_id, ServiceIntegration.user_id == user_id).with_for_update())
        if row and row.revision == revision and row.checking_until == lease:
            row.checking_until = 0
            row.error = error
            if result is not None and not error:
                row.result, row.checked_at = result, time.time()


def public(row, bookmark_ids=None):
    from app.services.proxmox.operations import capabilities
    config = dict(row.config)
    if bookmark_ids is not None:
        config['bookmark_ids'] = [key for key in config['bookmark_ids'] if key in bookmark_ids]
    data = {key: value for key, value in row.result.items() if not key.startswith('_')}
    tree = row.result.get('_permissions', {})
    for key in ('nodes', 'guests'):
        data[key] = [dict(resource, actions=capabilities(resource, row.result, tree) if config['enabled'] and config['controls'] and not row.error else []) for resource in data.get(key, [])]
    return {'id': row.id, 'provider': row.provider, 'config': config, 'has_token': bool(row.token_encrypted),
            'checked_at': row.checked_at, 'refreshing': row.checking_until > time.time(), 'next_check': row.next_check,
            'error': row.error, 'data': data}
