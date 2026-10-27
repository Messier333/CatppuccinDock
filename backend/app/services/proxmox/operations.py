"""Explicit Proxmox operations and resource-scoped effective permission checks."""
from app.services.proxmox.client import ProxmoxError, permitted, permissions, segment

ACTION_LABELS = {
    'start': '시작', 'shutdown': '정상 종료', 'reboot': '재부팅', 'stop': '강제 중지',
    'reset': '강제 재시작', 'suspend': '일시 중지', 'resume': '다시 시작',
    'snapshot': '스냅샷 생성', 'snapshot_delete': '스냅샷 삭제', 'rollback': '스냅샷 복원',
    'backup': '백업 실행', 'clone': '전체 복제', 'migrate': '노드 이동',
    'cpu': 'CPU 코어 변경', 'memory': '메모리 변경', 'onboot': '자동 시작 변경',
    'template': '템플릿으로 변환', 'delete': 'VM·컨테이너 삭제',
    'node_reboot': '노드 재부팅', 'node_shutdown': '노드 종료',
}
DANGEROUS = {'stop', 'reset', 'rollback', 'snapshot_delete', 'delete', 'template', 'node_reboot', 'node_shutdown'}


def capabilities(resource, inventory, tree):
    node = resource['node']
    if resource['type'] == 'node':
        return ['node_reboot', 'node_shutdown'] if resource['status'] == 'online' and permitted(tree, '/nodes/' + node, 'Sys.PowerMgmt') else []
    path = '/vms/' + str(resource['vmid'])
    allowed = lambda privilege: permitted(tree, path, privilege)
    actions = []
    stopped = resource['status'] == 'stopped'
    template = resource.get('template', False)
    if allowed('VM.PowerMgmt') and not template:
        actions += ['start'] if stopped else ['shutdown', 'reboot', 'stop']
        if resource['type'] == 'qemu' and not stopped:
            if resource.get('qmpstatus') in ('paused', 'suspended'):
                actions = ['resume', 'stop']
            else:
                actions += ['reset', 'suspend']
    if allowed('VM.Snapshot'):
        actions += ['snapshot', 'snapshot_delete']
    if allowed('VM.Snapshot') or allowed('VM.Snapshot.Rollback'):
        actions += ['rollback']
    if allowed('VM.Backup') and any(permitted(tree, '/storage/' + s['storage'], 'Datastore.AllocateSpace') and s['node'] == node for s in inventory.get('storage', [])):
        actions += ['backup']
    if allowed('VM.Clone'):
        actions += ['clone']
    if allowed('VM.Migrate') and any(n['node'] != node and n['status'] == 'online' for n in inventory.get('nodes', [])):
        actions += ['migrate']
    for key, privilege in [('cpu', 'VM.Config.CPU'), ('memory', 'VM.Config.Memory'), ('onboot', 'VM.Config.Options')]:
        if allowed(privilege):
            actions.append(key)
    if stopped and allowed('VM.Allocate'):
        actions += ['delete']
        if not template:
            actions += ['template']
    return actions


def resource_path(resource):
    node = segment(resource['node'])
    if resource['type'] == 'node':
        return '/nodes/' + node
    kind = resource['type']
    if kind not in ('qemu', 'lxc'):
        raise ProxmoxError('지원하지 않는 리소스입니다.', 422)
    return f'/nodes/{node}/{kind}/{int(resource["vmid"])}'


def lookup(inventory, resource_id):
    resource = next((r for key in ('nodes', 'guests') for r in inventory.get(key, []) if r['id'] == resource_id), None)
    if not resource:
        raise ProxmoxError('허용된 노드에서 리소스를 찾을 수 없습니다.', 404)
    return resource


def authoritative(client, config, resource_id):
    from app.services.proxmox import inventory
    data = inventory(client, config)
    resource = lookup(data, resource_id)
    path = '/nodes/' + resource['node'] if resource['type'] == 'node' else '/vms/' + str(resource['vmid'])
    tree = permissions(client)
    tree.update(permissions(client, path))
    if resource['type'] != 'node':
        current = client.request('GET', resource_path(resource) + '/status/current')
        if not isinstance(current, dict):
            raise ProxmoxError('Proxmox 상태 응답을 확인하세요.')
        resource.update({key: current[key] for key in ('status', 'qmpstatus', 'lock') if key in current})
    return resource, data, tree


def integer(parameters, key, minimum, maximum):
    value = parameters.get(key)
    if isinstance(value, bool) or not isinstance(value, (str, int)) or not str(value).isascii() or not str(value).isdigit():
        raise ProxmoxError('숫자 입력을 확인하세요.', 422)
    result = int(value)
    if not minimum <= result <= maximum:
        raise ProxmoxError('허용된 숫자 범위를 확인하세요.', 422)
    return result


def plan(client, config, request):
    """Run both at preview and execution; never trust cached/browser capabilities."""
    if not config['enabled'] or not config['controls']:
        raise ProxmoxError('이 연동의 제어 기능이 꺼져 있습니다.', 403)
    resource, data, tree = authoritative(client, config, request.resource)
    action, parameters = request.action, request.parameters
    if action not in capabilities(resource, data, tree):
        raise ProxmoxError('현재 권한 또는 리소스 상태에서 사용할 수 없는 기능입니다.', 403)
    if resource.get('lock'):
        raise ProxmoxError('리소스가 잠겨 있습니다. 기존 작업이 끝난 후 다시 시도하세요.', 409)
    base, method, path, body = resource_path(resource), 'POST', '', {}
    expected = set()
    if action.startswith('node_'):
        path, body = base + '/status', {'command': action.removeprefix('node_')}
    elif action in ('start', 'shutdown', 'reboot', 'stop', 'reset', 'suspend', 'resume'):
        path = base + '/status/' + action
    elif action in ('snapshot', 'snapshot_delete', 'rollback'):
        expected = {'snapname'}
        name = segment(parameters.get('snapname'))
        if name == 'current' or not name[0].isalpha() or len(name) > 40:
            raise ProxmoxError('스냅샷 이름은 영문으로 시작하는 40자 이내 식별자로 입력하세요.', 422)
        path = base + '/snapshot'
        if action == 'snapshot':
            body = {'snapname': name}
        else:
            snapshots = client.request('GET', path)
            if not isinstance(snapshots, list) or not any(s.get('name') == name for s in snapshots if isinstance(s, dict)):
                raise ProxmoxError('해당 스냅샷을 찾을 수 없습니다.', 404)
            path += '/' + name
            if action == 'rollback':
                path += '/rollback'
            else:
                method = 'DELETE'
    elif action in ('cpu', 'memory', 'onboot'):
        expected = {'value'}
        value = integer(parameters, 'value', 0 if action == 'onboot' else 1 if action == 'cpu' else 16, 1 if action == 'onboot' else 128 if action == 'cpu' else 1048576)
        key = {'cpu': 'cores', 'memory': 'memory', 'onboot': 'onboot'}[action]
        path, method, body = base + '/config', 'PUT', {key: value}
    elif action in ('template', 'delete'):
        path = base + ('/template' if action == 'template' else '')
        if action == 'delete':
            method = 'DELETE'
    elif action == 'migrate':
        expected = {'target'}
        target = segment(parameters.get('target'))
        if not any(n['node'] == target and n['node'] != resource['node'] and n['status'] == 'online' for n in data['nodes']):
            raise ProxmoxError('이동할 수 있는 노드를 선택하세요.', 422)
        path, body = base + '/migrate', {'target': target}
        if resource['status'] == 'running':
            body['online' if resource['type'] == 'qemu' else 'restart'] = 1
    elif action in ('clone', 'backup'):
        expected = {'storage'} | ({'newid', 'name'} if action == 'clone' else set())
        storage = segment(parameters.get('storage'))
        tree.update(permissions(client, '/storage/' + storage))
        if not any(s['storage'] == storage and s['node'] == resource['node'] for s in data['storage']) or not permitted(tree, '/storage/' + storage, 'Datastore.AllocateSpace'):
            raise ProxmoxError('스토리지 할당 권한이 없습니다.', 403)
        if action == 'backup':
            path = '/nodes/' + resource['node'] + '/vzdump'
            body = {'vmid': resource['vmid'], 'storage': storage, 'mode': 'snapshot', 'compress': 'zstd'}
        else:
            newid = integer(parameters, 'newid', 100, 999999999)
            target_tree = permissions(client, '/vms/' + str(newid))
            if not permitted(target_tree, '/vms/' + str(newid), 'VM.Allocate'):
                raise ProxmoxError('새 VM ID를 할당할 권한이 없습니다.', 403)
            if any(g['vmid'] == newid for g in data['guests']):
                raise ProxmoxError('이미 사용 중인 VM ID입니다.', 409)
            name = segment(parameters.get('name'))
            path = base + '/clone'
            body = {'newid': newid, 'name' if resource['type'] == 'qemu' else 'hostname': name, 'storage': storage, 'full': 1}
    if set(parameters) != expected or not path:
        raise ProxmoxError('작업에 필요한 입력 항목을 확인하세요.', 422)
    return {'resource': resource, 'method': method, 'path': path, 'body': body, 'action': action,
            'label': ACTION_LABELS[action], 'dangerous': action in DANGEROUS,
            'confirmation': str(resource['vmid']) if resource['type'] != 'node' else resource['node']}
