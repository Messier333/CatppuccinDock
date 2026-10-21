"""Read-only adapters for reverse proxy host inventories."""
import ipaddress
import json
import re
from urllib.parse import urlsplit

import httpx
from fastapi import HTTPException
from pydantic import HttpUrl

from app.core.security import cipher


MAX_HOSTS = 1000
MAX_BYTES = 2 * 1024 * 1024


def url_key(value):
    """Match the canonical form used by manually edited bookmarks, too."""
    try:
        return str(HttpUrl(value))
    except ValueError:
        return value


def public_source(source):
    return {key: getattr(source, key) for key in ('id', 'name', 'provider', 'base_url', 'verify_tls', 'custom_api')} | {'has_token': bool(source.token_encrypted)}


def read_json(client, path, params=None):
    with client.stream('GET', path, params=params) as response:
        if response.status_code in (401, 403):
            raise HTTPException(502, 'API 인증에 실패했습니다. 토큰과 읽기 권한을 확인해 주세요.')
        if not 200 <= response.status_code < 300:
            raise HTTPException(502, f'서비스 API 응답이 올바르지 않습니다 (HTTP {response.status_code}). 기본 주소와 서비스 종류를 확인해 주세요.')
        body = bytearray()
        for chunk in response.iter_bytes():
            body.extend(chunk)
            if len(body) > MAX_BYTES:
                raise HTTPException(502, 'API 응답이 너무 큽니다. 한 번에 2MB까지 읽을 수 있습니다.')
    try:
        return json.loads(body)
    except (ValueError, UnicodeError) as error:
        raise HTTPException(502, 'API에서 JSON을 받지 못했습니다. 관리 서비스의 주소를 확인해 주세요.') from error


def fetch_hosts(source):
    config = source.custom_api or {}
    headers = {'Accept': 'application/json'}
    if source.provider != 'custom' or config.get('auth_type') != 'none':
        token = cipher().decrypt(source.token_encrypted.encode()).decode()
        if source.provider == 'custom' and config.get('auth_type') == 'header':
            headers[config['auth_header']] = token
        else:
            headers['Authorization'] = 'Bearer '+token
    try:
        with httpx.Client(base_url=source.base_url.rstrip('/')+'/', headers=headers,
                          timeout=httpx.Timeout(10, connect=5), verify=source.verify_tls, follow_redirects=False, trust_env=False) as client:
            if source.provider == 'custom':
                result = field_value(read_json(client, config['endpoint']), config['items_path'])
            elif source.provider == 'npm':
                result = read_json(client, 'api/nginx/proxy-hosts')
            elif source.provider == 'zoraxy':
                result = read_json(client, 'plugin/api/proxy/list', {'type': 'host'})
            else:
                result = []
                for page in range(1, 11):
                    data = read_json(client, 'api/v1/proxy-hosts', {'page': page, 'per_page': 100})
                    if not isinstance(data, dict) or not isinstance(data.get('data'), list):
                        raise HTTPException(502, 'Nginx Proxy Guard의 호스트 목록 형식이 올바르지 않습니다.')
                    result.extend(data['data'])
                    total_pages = data.get('total_pages')
                    if not isinstance(total_pages, int) or not 0 <= total_pages <= 10:
                        raise HTTPException(502, '페이지 정보가 올바르지 않거나 호스트가 1,000개를 초과합니다.')
                    if page >= total_pages:
                        break
            if not isinstance(result, list) or any(not isinstance(host, (dict, str) if source.provider == 'custom' else dict) for host in result):
                raise HTTPException(502, '호스트 목록 API 형식을 확인해 주세요. 이 버전의 서비스 API와 호환되지 않습니다.')
            if len(result) > MAX_HOSTS:
                raise HTTPException(502, '한 번에 최대 1,000개의 호스트를 가져올 수 있습니다.')
            return result
    except httpx.TimeoutException as error:
        raise HTTPException(502, '서비스 API 응답 시간이 초과됐습니다. 서버에서 접속 가능한 주소인지 확인해 주세요.') from error
    except httpx.HTTPError as error:
        raise HTTPException(502, '서비스 API에 연결하지 못했습니다. 주소와 TLS 인증서를 확인해 주세요.') from error


def domain_url(domain, scheme, port):
    if not isinstance(domain, str) or not domain or len(domain) > 253 or any(char in domain for char in '*/?#@\\'):
        return None
    try:
        parsed = urlsplit('//'+domain.strip())
        if not parsed.hostname or parsed.path or parsed.port is not None:
            return None
        host = parsed.hostname.encode('idna').decode().lower().rstrip('.')
        try:
            address = ipaddress.ip_address(host)
            if address.version == 6:
                host = '['+host+']'
        except ValueError:
            if not all(re.fullmatch(r'[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?', part) for part in host.split('.')):
                return None
        return f'{scheme}://{host}'+(f':{port}' if port else '')
    except (ValueError, UnicodeError):
        return None


def field_value(item, path):
    for part in path.split('.') if path else []:
        if isinstance(item, dict):
            item = item.get(part)
        elif isinstance(item, list) and part.isdigit() and int(part) < len(item):
            item = item[int(part)]
        else:
            return None
    return item


def normalize_custom(hosts, options, config):
    entries, seen, skipped = [], set(), 0
    for host in hosts:
        values = field_value(host, config['url_field'])
        name = field_value(host, config['name_field']) if config['name_field'] else None
        for value in values if isinstance(values, list) else [values]:
            if config['url_format'] == 'domain':
                value = domain_url(value, 'https' if options.scheme == 'auto' else options.scheme, options.public_port)
            try:
                parsed = HttpUrl(value)
                if parsed.username or parsed.password or len(str(parsed)) > 2048:
                    raise ValueError('Invalid bookmark URL')
                url = str(parsed)
            except (ValueError, TypeError):
                skipped += 1
                continue
            if url in seen:
                skipped += 1
                continue
            seen.add(url)
            label = name.strip() if isinstance(name, str) else ''
            entries.append({'id': str(len(entries)), 'name': (label or urlsplit(url).hostname)[:120], 'url': url})
            if len(entries) > MAX_HOSTS:
                raise HTTPException(502, '한 번에 최대 1,000개의 링크를 가져올 수 있습니다.')
    if hosts and not entries:
        raise HTTPException(502, '유효한 링크가 없습니다. URL 필드 경로와 URL/도메인 형식을 확인해 주세요.')
    return entries, skipped


def normalize_hosts(provider, hosts, options, custom_api=None):
    if provider == 'custom':
        return normalize_custom(hosts, options, custom_api)
    if provider == 'zoraxy' and options.scheme == 'auto':
        raise HTTPException(422, 'Zoraxy는 목록 API에 전역 TLS 설정이 없어 HTTP 또는 HTTPS를 직접 선택해 주세요.')
    entries, seen, skipped = [], set(), 0
    for host in hosts:
        if provider == 'zoraxy':
            disabled = host.get('Disabled', False) or host.get('ProxyType', 1) != 1
            aliases = host.get('MatchingDomainAlias') or []
            if not isinstance(aliases, list) or not isinstance(host.get('RootOrMatchingDomain'), str):
                raise HTTPException(502, 'Zoraxy의 호스트 목록 형식이 올바르지 않습니다.')
            domains = [host['RootOrMatchingDomain']] + aliases
            secure = not host.get('BypassGlobalTLS', False)
        else:
            disabled = not host.get('enabled', True) or host.get('proxy_type', 'http') == 'stream'
            domains = host.get('domain_names')
            secure = bool(host.get('ssl_enabled') or host.get('ssl_force_https') or host.get('ssl_forced') or host.get('certificate_id'))
        if disabled:
            skipped += 1
            continue
        if not isinstance(domains, list):
            raise HTTPException(502, 'API의 도메인 목록 형식이 올바르지 않습니다.')
        scheme = options.scheme if options.scheme != 'auto' else ('https' if secure else 'http')
        # A Zoraxy rule that bypasses global TLS is HTTP-only.
        if provider == 'zoraxy' and host.get('BypassGlobalTLS'):
            scheme = 'http'
        for domain in domains:
            url = domain_url(domain, scheme, options.public_port)
            if not url or url in seen:
                skipped += 1
                continue
            seen.add(url)
            entries.append({'id': str(len(entries)), 'name': urlsplit(url).hostname[:120], 'url': url})
            if len(entries) > MAX_HOSTS:
                raise HTTPException(502, '도메인 별칭을 포함해 최대 1,000개의 링크까지 미리 볼 수 있습니다.')
    return entries, skipped
