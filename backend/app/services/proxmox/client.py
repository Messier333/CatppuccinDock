"""Bounded HTTPS transport with pinned DNS and no redirects or ambient credentials."""
import http.client
import json
import socket
import ssl
import time
from urllib.parse import urlencode, urlsplit
from cryptography.fernet import InvalidToken

from app.core.security import cipher
from app.services.monitoring import pinned_http_connection, safe_addresses, safe_request_target, secure_tls_context


class ProxmoxError(ValueError):
    def __init__(self, message, status=502):
        super().__init__('Proxmox API request failed')
        self.public_message = message
        self.status = status


class Client:
    def __init__(self, config, encrypted):
        self.config = config
        self.encrypted = encrypted

    def request(self, method, endpoint, parameters=None):
        """Only internal adapters supply method/endpoint; API callers supply typed values."""
        parsed = urlsplit(self.config['base_url'])
        host, port = parsed.hostname, parsed.port or 443
        sock = connection = None
        try:
            context = secure_tls_context()
            if self.config.get('ca_certificate'):
                context.load_verify_locations(cadata=self.config['ca_certificate'])
            addresses = safe_addresses(host, port, self.config['allow_private'])
            sock = socket.create_connection((addresses[0], port), timeout=5)
            sock = context.wrap_socket(sock, server_hostname=host)
            connection = pinned_http_connection()
            connection.sock = sock
            body = urlencode(parameters or {}).encode('ascii')
            query = body.decode('ascii') if method == 'GET' else ''
            path = safe_request_target('/api2/json' + endpoint, query)
            connection.putrequest(method, path, skip_host=True, skip_accept_encoding=True)
            host_header = ('[' + host + ']' if ':' in host else host) + ':' + str(port)
            token = cipher().decrypt(self.encrypted.encode()).decode()
            headers = {'Host': host_header, 'Accept': 'application/json', 'Connection': 'close',
                       'Authorization': 'PVEAPIToken=' + self.config['token_id'] + '=' + token,
                       'User-Agent': 'CatppuccinDock-Proxmox/1.0'}
            if method != 'GET':
                headers |= {'Content-Type': 'application/x-www-form-urlencoded', 'Content-Length': str(len(body))}
            for key, value in headers.items():
                connection.putheader(key, value)
            connection.endheaders(body if method != 'GET' else None)
            response = connection.getresponse()
            if response.status in (401, 403):
                raise ProxmoxError('API 토큰이 만료됐거나 이 작업에 필요한 권한이 없습니다.', 403)
            if not 200 <= response.status < 300:
                # Upstream bodies may contain secrets, configs and untrusted HTML.
                raise ProxmoxError(f'Proxmox가 요청을 거절했습니다 (HTTP {response.status}). 상태·잠금·스토리지·권한을 확인하세요.')
            limit, body, deadline = 2 * 1024 * 1024, bytearray(), time.monotonic() + 10
            while True:
                if time.monotonic() > deadline:
                    raise ProxmoxError('Proxmox 응답 시간이 초과됐습니다.')
                chunk = response.read1(min(65536, limit + 1 - len(body)))
                body.extend(chunk)
                if len(body) > limit:
                    raise ProxmoxError('Proxmox 응답이 2MB를 초과합니다.')
                if not chunk:
                    break
            return json.loads(body)['data']
        except ProxmoxError:
            raise
        except (OSError, ssl.SSLError, http.client.HTTPException, ValueError, KeyError, TypeError, UnicodeError, InvalidToken) as error:
            raise ProxmoxError('Proxmox 연결·인증서·응답 형식을 확인하세요.') from error
        finally:
            if connection:
                connection.close()
            elif sock:
                sock.close()


def segment(value):
    """Resource identifiers from an upstream server are untrusted too."""
    if not isinstance(value, str) or not 1 <= len(value) <= 128 or value in ('.', '..') or not all(c.isascii() and (c.isalnum() or c in '-_.') for c in value):
        raise ProxmoxError('Proxmox 리소스 식별자를 확인하세요.')
    return value


def permissions(client, path=None):
    result = client.request('GET', '/access/permissions', {'path': path} if path else None)
    if not isinstance(result, dict) or len(result) > 20000:
        raise ProxmoxError('Proxmox 권한 응답 형식을 확인하세요.')
    return {path: result.get(path, {})} if path else result


def permitted(tree, path, privilege):
    # A zero propagate flag still grants the privilege on that exact path.
    matches = [(prefix, values) for prefix, values in tree.items() if isinstance(values, dict) and (prefix == path or path.startswith(prefix.rstrip('/') + '/'))]
    if matches:
        prefix, values = max(matches, key=lambda item: len(item[0]))
        return privilege in values and (prefix == path or values[privilege] in (1, True))
    return False
