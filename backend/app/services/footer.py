"""Footer layout and bounded, server-side monitoring integrations."""
import http.client
import json
import math
import secrets
import socket
import ssl
import time
from urllib.parse import urlencode, urlsplit
from cryptography.fernet import InvalidToken
from fastapi import HTTPException
from sqlalchemy import select
from app.core.security import cipher
from app.db.models import FooterMetric, Setting
from app.db.session import SessionLocal
from app.schemas.footer import BASE_ITEMS, REQUIRED_ITEMS
from app.services.monitoring import safe_addresses


class AuthenticationFailure(ValueError):
    pass


def allowed_items(db, user):
    metrics = list(db.scalars(select(FooterMetric).order_by(FooterMetric.id)))
    return BASE_ITEMS + ['metric:' + row.id for row in metrics if row.config['enabled'] and (user.role == 'admin' or row.config['audience'] == 'all')]


def layout(db, user):
    allowed = allowed_items(db, user)
    common = db.get(Setting, 'footer')
    saved = common.value if common else {}
    order = [key for key in saved.get('order', []) if key in allowed]
    order += [key for key in allowed if key not in order]
    hidden = [key for key in saved.get('hidden', []) if key in allowed and key not in REQUIRED_ITEMS]
    own = db.get(Setting, f'footer:{user.id}')
    if own:
        personal = [key for key in own.value.get('order', []) if key in order]
        order = personal + [key for key in order if key not in personal]
    return {'order': order, 'hidden': hidden}


def public_metric(row):
    return dict(row.config, id=row.id, has_token=bool(row.token_encrypted), checked_at=row.checked_at, result=row.result)


def json_request(url, private, token=''):
    """Pin validated DNS, preserve TLS SNI, never forward cookies or redirects."""
    parsed = urlsplit(url)
    host = parsed.hostname
    port = parsed.port or (443 if parsed.scheme == 'https' else 80)
    addresses = safe_addresses(host, port, private)
    sock = None
    connection = None
    try:
        sock = socket.create_connection((addresses[0], port), timeout=6)
        if parsed.scheme == 'https':
            sock = ssl.create_default_context().wrap_socket(sock, server_hostname=host)
        connection = http.client.HTTPConnection(host, port, timeout=6)
        connection.sock = sock
        path = parsed.path or '/'
        if parsed.query: path += '?' + parsed.query
        host_header = ('[' + host + ']' if ':' in host else host) + (':' + str(parsed.port) if parsed.port else '')
        connection.putrequest('GET', path, skip_host=True, skip_accept_encoding=True)
        for key, value in {'Host': host_header, 'Accept': 'application/json', 'Connection': 'close', 'User-Agent': 'CatppuccinDock-Metrics/1.0', **({'Authorization': 'Bearer ' + token} if token else {})}.items():
            connection.putheader(key, value)
        connection.endheaders()
        response = connection.getresponse()
        if response.status in (401, 403): raise AuthenticationFailure('API 토큰과 조회 권한을 확인하세요.')
        if not 200 <= response.status < 300: raise ValueError('API 주소와 서비스 응답을 확인하세요.')
        limit = 2 * 1024 * 1024
        body = bytearray()
        deadline = time.monotonic() + 10
        while True:
            if time.monotonic() > deadline: raise ValueError('API 응답 시간이 초과됐습니다.')
            chunk = response.read(min(65536, limit + 1 - len(body)))
            body.extend(chunk)
            if len(body) > limit: raise ValueError('API 응답이 2MB를 초과합니다.')
            if not chunk: break
        return json.loads(body)
    finally:
        if connection: connection.close()
        elif sock: sock.close()


def number(value):
    if isinstance(value, bool): return None
    try: result = float(value)
    except (ValueError, TypeError, OverflowError): return None
    return result if math.isfinite(result) else None


def collect(config, token):
    base = config['base_url'].rstrip('/')
    if config['provider'] == 'kuma':
        data = json_request(base + '/api/status-page/heartbeat/' + config['slug'], config['allow_private'], token)
        beats = data.get('heartbeatList', {}).get(config['monitor_id'], [])
        if not isinstance(beats, list) or not beats: raise ValueError('공개 상태 페이지의 모니터 ID와 기록을 확인하세요.')
        if any(not isinstance(beat, dict) for beat in beats): raise ValueError('상태 페이지 응답 형식을 확인하세요.')
        # Kuma returns the most recent heartbeat first in some versions.
        beats = sorted(beats, key=lambda beat: str(beat.get('time', '')))[-100:]
        status = number(beats[-1].get('status'))
        state = {0: 'down', 1: 'up', 2: 'pending', 3: 'maintenance'}.get(status, 'pending')
        if config['metric'] == 'uptime':
            uptime = number(data.get('uptimeList', {}).get(config['monitor_id'] + '_24'))
            value = uptime * 100 if uptime is not None else None
            points = []
        else:
            field = 'ping' if config['metric'] == 'latency' else 'status'
            points = [number(beat.get(field)) for beat in beats]
            value = points[-1]
        return {'available': value is not None, 'value': value, 'points': points, 'state': state}
    now = int(time.time())
    endpoint = '/api/v1/query_range'
    if config['provider'] == 'grafana': endpoint = '/api/datasources/proxy/uid/' + config['datasource_uid'] + endpoint
    query = urlencode({'query': config['query'], 'start': now - config['window'], 'end': now, 'step': max(15, math.ceil(config['window'] / 90)), 'timeout': '5s'})
    data = json_request(base + endpoint + '?' + query, config['allow_private'], token)
    if data.get('status') != 'success': raise ValueError('PromQL 조회가 실패했습니다. 쿼리와 데이터 소스를 확인하세요.')
    result = data.get('data', {}).get('result', [])
    if not isinstance(result, list) or len(result) != 1: raise ValueError('한 개의 시계열이 필요합니다. sum 또는 avg 등으로 집계하세요.')
    values = result[0].get('values', [])
    if not isinstance(values, list) or len(values) > 1000: raise ValueError('시계열 응답 형식을 확인하세요.')
    if any(not isinstance(point, list) or len(point) != 2 for point in values): raise ValueError('시계열 응답 형식을 확인하세요.')
    points = [number(point[1]) for point in values][-120:]
    value = points[-1] if points else None
    return {'available': value is not None, 'value': value, 'points': points, 'state': 'up' if value is not None else 'pending'}


def run_check(metric_id, force=False):
    with SessionLocal.begin() as db:
        row = db.scalar(select(FooterMetric).where(FooterMetric.id == metric_id).with_for_update())
        if not row: return
        now = time.time()
        if force and row.attempted_at > now - 15: raise HTTPException(409, '잠시 후 다시 확인하세요.')
        if not force and (not row.config['enabled'] or row.next_check > now): return
        if row.next_check > now and not row.checked_at: return
        config, token, revision = row.config, row.token_encrypted, row.revision
        row.attempted_at = now
        row.next_check = now + max(60, config['interval'])
    auth_failure = False
    try:
        result = collect(config, cipher().decrypt(token.encode()).decode() if token else '')
    except AuthenticationFailure:
        auth_failure = True
        result = {'available': False, 'state': 'pending', 'value': None, 'points': [], 'detail': 'API 토큰과 조회 권한을 확인하세요.'}
    except ValueError as error:
        # Only locally written validation messages are exposed; JSON errors can contain response data.
        detail = str(error) if type(error) is ValueError else 'API 응답 형식을 확인하세요.'
        result = {'available': False, 'state': 'pending', 'value': None, 'points': [], 'detail': detail[:160]}
    except (OSError, http.client.HTTPException, InvalidToken, KeyError, TypeError, AttributeError, UnicodeError):
        result = {'available': False, 'state': 'pending', 'value': None, 'points': [], 'detail': 'API 연결·인증서·응답 형식을 확인하세요.'}
    with SessionLocal.begin() as db:
        row = db.scalar(select(FooterMetric).where(FooterMetric.id == metric_id).with_for_update())
        if row and row.revision == revision:
            row.result, row.checked_at = result, time.time()
            if auth_failure: row.next_check = time.time() + 86400


def run_due():
    with SessionLocal() as db:
        ids = [row.id for row in db.scalars(select(FooterMetric).where(FooterMetric.next_check <= time.time()).order_by(FooterMetric.next_check)) if row.config['enabled']][:8]
    from concurrent.futures import ThreadPoolExecutor
    with ThreadPoolExecutor(max_workers=4) as pool: list(pool.map(run_check, ids))
