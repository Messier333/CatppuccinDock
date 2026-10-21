"""Bounded public-page previews, with pinned DNS and no browser credentials."""
import http.client
import re
import socket
import ssl
import time
from html.parser import HTMLParser
from threading import BoundedSemaphore
from urllib.parse import urljoin, urlsplit

from app.services.icons import collection_data
from app.services.monitoring import safe_addresses

slots = BoundedSemaphore(4)


class PageTitle(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.inside = False; self.parts = []; self.og = ''

    def handle_starttag(self, tag, attrs):
        values = dict(attrs)
        if tag == 'title': self.inside = True
        if tag == 'meta' and (values.get('property') or '').lower() == 'og:title': self.og = values.get('content') or ''

    def handle_endtag(self, tag):
        if tag == 'title': self.inside = False

    def handle_data(self, data):
        if self.inside: self.parts.append(data)

    @property
    def title(self):
        return re.sub(r'\s+', ' ', self.og or ''.join(self.parts)).strip()[:120]


def suggest_icon(url, title=''):
    host = urlsplit(url).hostname or ''
    aliases = {'youtu':'youtube','gmail':'gmail','github':'github','google':'google','duckduckgo':'duckduckgo', 'stackoverflow':'stackoverflow'}
    words = re.findall(r'[a-z0-9]+', host.lower()) + re.findall(r'[a-z0-9]+', title.lower())
    icons = collection_data('simple-icons')['icons']
    for word in words:
        word = aliases.get(word, word)
        if word not in ('www','com','net','org','app','io','test','local') and word in icons:
            return 'simple-icons:' + word
    return 'world'


def public_title(url):
    deadline = time.monotonic()+8
    for _ in range(3):
        parsed = urlsplit(url)
        if parsed.scheme not in ('http','https') or not parsed.hostname or parsed.username or parsed.password:
            raise ValueError('Invalid preview URL')
        port = parsed.port or (443 if parsed.scheme=='https' else 80)
        addresses = safe_addresses(parsed.hostname, port, False)
        remaining = deadline-time.monotonic()
        if remaining <= 0: raise ValueError('Preview timed out')
        sock = socket.create_connection((addresses[0],port),timeout=min(2,remaining))
        connection = None
        try:
            if parsed.scheme=='https': sock = ssl.create_default_context().wrap_socket(sock,server_hostname=parsed.hostname)
            connection = http.client.HTTPConnection(parsed.hostname,port,timeout=min(2,remaining)); connection.sock = sock
            host = ('['+parsed.hostname+']' if ':' in parsed.hostname else parsed.hostname) + (':'+str(parsed.port) if parsed.port else '')
            path = (parsed.path or '/') + ('?'+parsed.query if parsed.query else '')
            connection.putrequest('GET',path,skip_host=True,skip_accept_encoding=True)
            connection.putheader('Host',host);connection.putheader('User-Agent','CatppuccinDock-Preview/1.0')
            connection.putheader('Accept','text/html');connection.putheader('Connection','close');connection.endheaders()
            response = connection.getresponse()
            if response.status in (301,302,303,307,308):
                location = response.getheader('Location')
                if not location: raise ValueError('Missing redirect')
                url = urljoin(url,location); continue
            if response.status != 200 or 'text/html' not in response.getheader('Content-Type','').lower(): raise ValueError('No HTML title')
            body = response.read(131072)
            match = re.search(r'charset=["\s]*([a-zA-Z0-9_-]+)',response.getheader('Content-Type',''))
            parser = PageTitle(); parser.feed(body.decode(match.group(1) if match else 'utf-8',errors='replace'))
            return parser.title
        finally:
            if connection: connection.close()
            else: sock.close()
    raise ValueError('Too many redirects')


def preview(url):
    host = urlsplit(url).hostname or '새 북마크'
    title = ''
    if slots.acquire(blocking=False):
        try:
            try: title = public_title(url)
            except (OSError, ValueError, http.client.HTTPException, UnicodeError, LookupError): pass
        finally: slots.release()
    return {'url':url, 'name':title or host[:120], 'icon':suggest_icon(url,title), 'resolved':bool(title),
            'notice':'' if title else '주소를 바탕으로 이름과 아이콘을 채웠어요. 원하는 내용으로 수정할 수 있습니다.'}
