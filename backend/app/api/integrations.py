"""All integration routes enforce owner identity, including for portal admins."""
import json
import hashlib
import secrets
import ssl
import time
from urllib.parse import quote

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import delete, func, select

from app.api.dependencies import require_mutation_header, require_user
from app.core.security import cipher
from app.db.models import Bookmark, IntegrationTask, OperationPreview, ServiceIntegration, User
from app.db.session import SessionLocal
from app.schemas.proxmox import ActionRequest, ExecuteRequest, IntegrationData, Presentation
from app.services import proxmox
from app.services.proxmox.client import Client, ProxmoxError, permissions, permitted, secure_tls_context
from app.services.proxmox.operations import ACTION_LABELS, capabilities, lookup, plan, resource_path

router = APIRouter(prefix='/api/integrations/proxmox', dependencies=[Depends(require_user)])


def owned(db, integration_id, user, lock=False):
    query = select(ServiceIntegration).where(ServiceIntegration.id == integration_id, ServiceIntegration.user_id == user.id)
    row = db.scalar(query.with_for_update() if lock else query)
    if not row:
        raise HTTPException(404, '연동을 찾을 수 없습니다.')
    return row


def bookmark_ids(db, user):
    return set(db.scalars(select(Bookmark.id).where(Bookmark.user_id == user.id)))


def validate_bindings(db, payload, user, integration_id=None):
    if not set(payload.bookmark_ids).issubset(bookmark_ids(db, user)):
        raise HTTPException(404, '내 북마크에서 연결할 항목을 선택하세요.')
    for row in db.scalars(select(ServiceIntegration).where(ServiceIntegration.user_id == user.id)):
        if row.id != integration_id and set(row.config['bookmark_ids']).intersection(payload.bookmark_ids):
            raise HTTPException(409, '이미 다른 연동에 연결된 북마크입니다.')


def guard_edit(row):
    if row.action_until > time.time():
        raise HTTPException(409, '제어 요청이 전송 중입니다. 잠시 후 다시 시도하세요.')


@router.get('')
def listing(user: User = Depends(require_user)):
    with SessionLocal() as db:
        ids = bookmark_ids(db, user)
        return {'integrations': [proxmox.public(row, ids) for row in db.scalars(select(ServiceIntegration).where(ServiceIntegration.user_id == user.id).order_by(ServiceIntegration.id))],
                'actions': ACTION_LABELS}


def save(db, payload, user, integration_id=None):
    db.scalar(select(User).where(User.id == user.id).with_for_update())
    row = owned(db, integration_id, user, True) if integration_id else None
    if row:
        guard_edit(row)
    else:
        own_count = db.scalar(select(func.count()).select_from(ServiceIntegration).where(ServiceIntegration.user_id == user.id))
        total = db.scalar(select(func.count()).select_from(ServiceIntegration))
        if own_count >= 8 or total >= 64:
            raise HTTPException(409, 'Proxmox 연동 한도에 도달했습니다 (계정 8개 · 서버 64개).')
    validate_bindings(db, payload, user, integration_id)
    config = payload.model_dump(mode='json', exclude={'token'})
    if config['ca_certificate']:
        try:
            secure_tls_context().load_verify_locations(cadata=config['ca_certificate'])
        except (ssl.SSLError, ValueError) as error:
            raise HTTPException(422, '올바른 PEM CA 인증서를 입력하세요.') from error
    old = row.config if row else {}
    if not payload.token and (not row or old.get('base_url') != config['base_url'] or old.get('token_id') != config['token_id']):
        raise HTTPException(422, '새 연결 또는 주소·토큰 ID 변경에는 토큰 Secret을 다시 입력하세요.')
    if not row:
        row = ServiceIntegration(user_id=user.id)
    if payload.token:
        row.token_encrypted = cipher().encrypt(payload.token.encode()).decode()
    row.config, row.revision = config, secrets.token_hex(16)
    row.result, row.error, row.checked_at = {}, '', None
    row.next_check = row.checking_until = row.action_until = 0
    db.add(row)
    db.flush()
    return proxmox.public(row)


@router.post('', dependencies=[Depends(require_mutation_header)])
def create(payload: IntegrationData, user: User = Depends(require_user)):
    with SessionLocal.begin() as db:
        return save(db, payload, user)


@router.put('/{integration_id}', dependencies=[Depends(require_mutation_header)])
def update(integration_id: str, payload: IntegrationData, user: User = Depends(require_user)):
    with SessionLocal.begin() as db:
        return save(db, payload, user, integration_id)


@router.put('/{integration_id}/presentation', dependencies=[Depends(require_mutation_header)])
def presentation(integration_id: str, payload: Presentation, user: User = Depends(require_user)):
    with SessionLocal.begin() as db:
        db.scalar(select(User).where(User.id == user.id).with_for_update())
        row = owned(db, integration_id, user, True)
        validate_bindings(db, payload, user, integration_id)
        row.config = dict(row.config, **payload.model_dump(mode='json'))
        return proxmox.public(row)


@router.delete('/{integration_id}', dependencies=[Depends(require_mutation_header)])
def remove(integration_id: str, user: User = Depends(require_user)):
    with SessionLocal.begin() as db:
        row = owned(db, integration_id, user, True)
        guard_edit(row)
        db.execute(delete(IntegrationTask).where(IntegrationTask.integration_id == row.id))
        db.delete(row)
    return {'ok': True}


@router.post('/{integration_id}/refresh', dependencies=[Depends(require_mutation_header)])
def refresh(integration_id: str, user: User = Depends(require_user)):
    with SessionLocal() as db:
        owned(db, integration_id, user)
    try:
        proxmox.refresh(integration_id, user.id)
    except ProxmoxError as error:
        raise HTTPException(error.status, error.public_message) from error
    with SessionLocal() as db:
        return proxmox.public(owned(db, integration_id, user), bookmark_ids(db, user))


def enabled_client(row):
    if not row.config['enabled']:
        raise HTTPException(409, '꺼져 있는 연동입니다.')
    return Client(row.config, row.token_encrypted)


def reserve_details(db, row):
    if row.detail_after > time.time():
        raise HTTPException(429, '잠시 후 다시 확인하세요.')
    row.detail_after = time.time() + 1


def operation_fingerprint(operation):
    identity = {key: operation['resource'].get(key) for key in ('id', 'node', 'name', 'status', 'template')}
    values = {key: operation[key] for key in ('method', 'path', 'body')}
    return hashlib.sha256(json.dumps([identity, values], sort_keys=True).encode()).hexdigest()


@router.get('/{integration_id}/resource')
def resource_details(integration_id: str, resource: str, user: User = Depends(require_user)):
    with SessionLocal.begin() as db:
        row = owned(db, integration_id, user, True)
        reserve_details(db, row)
        client = enabled_client(row)
    try:
        # Refreshes are bounded independently; resource read never accepts paths.
        data = proxmox.inventory(client, row.config)
        resource_row = lookup(data, resource)
        path = '/nodes/' + resource_row['node'] if resource_row['type'] == 'node' else '/vms/' + str(resource_row['vmid'])
        tree = permissions(client)
        tree.update(permissions(client, path))
        snapshots = []
        if resource_row['type'] != 'node':
            current = client.request('GET', resource_path(resource_row) + '/status/current')
            if isinstance(current, dict):
                resource_row.update({key: current[key] for key in ('status', 'qmpstatus', 'lock') if key in current})
        if resource_row['type'] != 'node' and permitted(tree, path, 'VM.Audit'):
            response = client.request('GET', resource_path(resource_row) + '/snapshot')
            if isinstance(response, list):
                snapshots = [{key: s.get(key) for key in ('name', 'description', 'snaptime')} for s in response[:500] if isinstance(s, dict) and s.get('name') != 'current']
        return {'resource': resource_row, 'snapshots': snapshots, 'actions': capabilities(resource_row, data, tree) if row.config['controls'] else []}
    except ProxmoxError as error:
        raise HTTPException(error.status, error.public_message) from error


@router.post('/{integration_id}/intents', dependencies=[Depends(require_mutation_header)])
def preview(integration_id: str, payload: ActionRequest, user: User = Depends(require_user)):
    with SessionLocal.begin() as db:
        row = owned(db, integration_id, user, True)
        reserve_details(db, row)
        client = enabled_client(row)
    try:
        operation = plan(client, row.config, payload)
    except ProxmoxError as error:
        raise HTTPException(error.status, error.public_message) from error
    with SessionLocal.begin() as db:
        current = owned(db, integration_id, user, True)
        if current.revision != row.revision:
            raise HTTPException(409, '연결 설정이 변경됐습니다. 다시 확인하세요.')
        db.execute(delete(OperationPreview).where(OperationPreview.user_id == user.id, OperationPreview.kind == 'proxmox', OperationPreview.expires_at < time.time()))
        if db.scalar(select(func.count()).select_from(OperationPreview).where(OperationPreview.user_id == user.id, OperationPreview.kind == 'proxmox')) >= 12:
            raise HTTPException(429, '확인 대기 중인 작업이 많습니다. 잠시 후 시도하세요.')
        intent = secrets.token_hex(24)
        document = {'integration_id': row.id, 'request': payload.model_dump(), 'confirmation': operation['confirmation'], 'operation': operation_fingerprint(operation)}
        db.add(OperationPreview(id=intent, user_id=user.id, kind='proxmox', payload_encrypted=cipher().encrypt(json.dumps(document).encode()).decode(), fingerprint=row.revision, expires_at=time.time() + 120))
    return {'intent': intent, 'label': operation['label'], 'target': operation['resource']['name'],
            'confirmation': operation['confirmation'], 'dangerous': operation['dangerous'], 'parameters': payload.parameters, 'expires_in': 120}


@router.post('/{integration_id}/execute', dependencies=[Depends(require_mutation_header)])
def execute(integration_id: str, payload: ExecuteRequest, user: User = Depends(require_user)):
    # Consume the one-use intent BEFORE contacting Proxmox. Ambiguous network
    # failures must not automatically replay a destructive operation.
    with SessionLocal.begin() as db:
        row = owned(db, integration_id, user, True)
        guard_edit(row)
        intent = db.scalar(select(OperationPreview).where(OperationPreview.id == payload.intent, OperationPreview.user_id == user.id, OperationPreview.kind == 'proxmox').with_for_update())
        if not intent or intent.expires_at < time.time() or intent.fingerprint != row.revision:
            raise HTTPException(409, '작업 확인이 만료됐거나 이미 사용됐습니다. 다시 확인하세요.')
        document = json.loads(cipher().decrypt(intent.payload_encrypted.encode()))
        if document['integration_id'] != row.id or payload.confirmation != document['confirmation']:
            raise HTTPException(422, '확인할 대상 ID를 정확히 입력하세요.')
        count = db.scalar(select(func.count()).select_from(IntegrationTask).where(IntegrationTask.user_id == user.id, IntegrationTask.created_at > time.time() - 60))
        if count >= 10:
            raise HTTPException(429, '분당 제어 요청 한도에 도달했습니다.')
        active = db.scalar(select(func.count()).select_from(IntegrationTask).where(IntegrationTask.integration_id == row.id, IntegrationTask.state.in_(['running', 'submitting'])))
        if active >= 100:
            raise HTTPException(429, '진행 중인 작업이 많습니다. 기존 작업 결과를 확인하세요.')
        client = enabled_client(row)
        request = ActionRequest.model_validate(document['request'])
        task = IntegrationTask(integration_id=row.id, user_id=user.id, revision=row.revision, node='', action=request.action, target=request.resource)
        db.add(task)
        db.delete(intent)
        action_lease = time.time() + 180
        row.action_until = action_lease
        db.flush()
        task_id, revision = task.id, row.revision
    upid, state, detail, node = '', 'failed', '', ''
    try:
        operation = plan(client, row.config, request)
        if operation_fingerprint(operation) != document['operation']:
            raise ProxmoxError('확인 이후 대상이나 상태가 변경됐습니다. 다시 확인하세요.', 409)
        with SessionLocal.begin() as db:
            current = owned(db, integration_id, user, True)
            if current.revision != revision or current.action_until != action_lease:
                raise ProxmoxError('제어 요청 중 연결 설정이 변경됐습니다. 다시 확인하세요.', 409)
        node = operation['resource']['node']
        result = client.request(operation['method'], operation['path'], operation['body'])
        if isinstance(result, str) and result.startswith('UPID:') and len(result) <= 512 and all(32 < ord(c) < 127 for c in result):
            upid, state = result, 'running'
        elif result is None:
            state = 'ok'
        else:
            state, detail = 'unknown', '응답을 확인하지 못했습니다. Proxmox 작업 목록에서 결과를 확인하세요.'
    except ProxmoxError as error:
        state = 'failed' if error.status in (403, 404, 409, 422) else 'unknown'
        detail = error.public_message + (' 재실행 전에 Proxmox 작업 목록을 확인하세요.' if state == 'unknown' else '')
    finally:
        with SessionLocal.begin() as db:
            task = db.get(IntegrationTask, task_id)
            task.upid, task.state, task.detail, task.node = upid, state, detail[:240], node
            current = owned(db, integration_id, user, True)
            if current.revision == revision and current.action_until == action_lease:
                current.action_until = current.next_check = 0
            old_ids = list(db.scalars(select(IntegrationTask.id).where(IntegrationTask.integration_id == row.id, IntegrationTask.state.in_(['ok', 'failed', 'unknown'])).order_by(IntegrationTask.created_at.desc()).offset(100)))
            db.execute(delete(IntegrationTask).where(IntegrationTask.id.in_(old_ids)))
    return {'id': task_id, 'state': state, 'detail': detail[:240]}


def task_dict(row):
    return {key: getattr(row, key) for key in ('id', 'action', 'target', 'state', 'detail', 'created_at')}


@router.get('/{integration_id}/tasks')
def tasks(integration_id: str, user: User = Depends(require_user)):
    with SessionLocal() as db:
        owned(db, integration_id, user)
        return [task_dict(row) for row in db.scalars(select(IntegrationTask).where(IntegrationTask.integration_id == integration_id, IntegrationTask.user_id == user.id).order_by(IntegrationTask.created_at.desc()).limit(100))]


@router.post('/{integration_id}/tasks/{task_id}/refresh', dependencies=[Depends(require_mutation_header)])
def task_status(integration_id: str, task_id: str, user: User = Depends(require_user)):
    with SessionLocal.begin() as db:
        row = owned(db, integration_id, user)
        task = db.scalar(select(IntegrationTask).where(IntegrationTask.id == task_id, IntegrationTask.integration_id == row.id, IntegrationTask.user_id == user.id).with_for_update())
        if not task:
            raise HTTPException(404, '작업을 찾을 수 없습니다.')
        if task.revision != row.revision:
            raise HTTPException(409, '연결 정보가 바뀌었습니다. 이전 작업은 Proxmox에서 확인하세요.')
        if task.state != 'running' or task.checked_at > time.time() - 5:
            return task_dict(task)
        task.checked_at = time.time()
        client = enabled_client(row)
    try:
        response = client.request('GET', '/nodes/' + task.node + '/tasks/' + quote(task.upid, safe='') + '/status')
        if not isinstance(response, dict):
            raise ProxmoxError('작업 응답을 확인하세요.')
        with SessionLocal.begin() as db:
            current = db.get(IntegrationTask, task_id)
            if current and current.revision == row.revision:
                if response.get('status') == 'stopped':
                    current.state = 'ok' if response.get('exitstatus') == 'OK' else 'failed'
                    current.detail = '' if current.state == 'ok' else 'Proxmox 작업이 실패했습니다. Proxmox 작업 로그를 확인하세요.'
                return task_dict(current)
    except ProxmoxError as error:
        raise HTTPException(error.status, error.public_message) from error
