"""Bounded HTTPS downloads with pinned public DNS and no user credentials."""
import socket
import time
from urllib.parse import urljoin, urlsplit

from app.services.monitoring import pinned_http_connection, safe_addresses, safe_request_target, secure_tls_context


class RemoteMediaError(ValueError):
    def __init__(self, message, status=502):
        super().__init__(message)
        self.status = status


def https_url(url):
    try:
        parsed = urlsplit(url)
        if (len(url) > 2048 or parsed.scheme != 'https' or not parsed.hostname
                or parsed.port not in (None, 443) or parsed.username or parsed.password
                or any(ord(character) < 32 for character in url)):
            raise ValueError('Invalid public media URL')
        return parsed
    except (ValueError, TypeError) as error:
        raise RemoteMediaError('안전한 HTTPS GIF 주소가 아닙니다.') from error


def fetch_public(url, *, max_bytes, accept, timeout=15, on_chunk=None):
    size_error = (f'원본 GIF가 {max_bytes // (1024*1024)}MB 제한을 넘었습니다.' if accept == 'image/gif'
                  else 'GIF 검색 응답이 너무 큽니다. 다른 검색어나 제공처를 선택해 주세요.')
    deadline = time.monotonic() + timeout
    for _ in range(4):
        parsed = https_url(url)
        addresses = safe_addresses(parsed.hostname, 443, False)
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise RemoteMediaError('GIF 서비스 응답 시간이 초과되었습니다.', 504)
        sock = socket.create_connection((addresses[0], 443), timeout=min(4, remaining))
        connection = None
        try:
            sock = secure_tls_context().wrap_socket(sock, server_hostname=parsed.hostname)
            connection = pinned_http_connection()
            connection.sock = sock
            path = safe_request_target(parsed.path, parsed.query)
            connection.putrequest('GET', path, skip_host=True, skip_accept_encoding=True)
            connection.putheader('Host', parsed.hostname)
            connection.putheader('User-Agent', 'CatppuccinDock/1.0 (self-hosted bookmark portal)')
            connection.putheader('Accept', accept)
            connection.putheader('Accept-Encoding', 'identity')
            connection.putheader('Connection', 'close')
            connection.endheaders()
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise RemoteMediaError('GIF 서비스 응답 시간이 초과되었습니다.', 504)
            sock.settimeout(min(12, remaining))
            response = connection.getresponse()
            if response.status in (301, 302, 303, 307, 308):
                location = response.getheader('Location')
                if not location:
                    raise RemoteMediaError('GIF 다운로드 주소가 올바르지 않습니다.')
                url = urljoin(url, location)
                continue
            if response.status != 200:
                raise RemoteMediaError('GIF 서비스 요청을 완료하지 못했습니다.', 429 if response.status == 429 else 404 if response.status == 404 else 502)
            length = response.getheader('Content-Length', '')
            if length.isdecimal() and int(length) > max_bytes:
                raise RemoteMediaError(size_error, 413)
            if response.getheader('Content-Encoding', 'identity').lower() not in ('', 'identity'):
                raise RemoteMediaError('압축된 GIF 응답은 지원하지 않습니다.')
            content_type = response.getheader('Content-Type', '').split(';', 1)[0].strip().lower()
            if content_type != accept:
                raise RemoteMediaError('GIF 서비스가 지원하지 않는 형식을 반환했습니다.', 422)
            data = bytearray()
            while True:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    raise RemoteMediaError('GIF 서비스 응답 시간이 초과되었습니다.', 504)
                sock.settimeout(min(8, remaining))
                chunk = response.read(min(65536, max_bytes + 1 - len(data)))
                if not chunk:
                    break
                data.extend(chunk)
                if on_chunk:
                    on_chunk(len(chunk))
                if len(data) > max_bytes:
                    raise RemoteMediaError(size_error, 413)
                if response.isclosed():
                    break
            return bytes(data)
        finally:
            if connection:
                connection.close()
            else:
                sock.close()
    raise RemoteMediaError('GIF 다운로드 주소가 너무 여러 번 변경되었습니다.')
