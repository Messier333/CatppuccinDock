"""GIF wallpaper adapters for the providers' public search/download pages."""
from html.parser import HTMLParser
import re
from urllib.parse import quote, urlencode, urljoin, urlsplit

from app.schemas.backgrounds import BackgroundSource
from app.services.media.remote_media import RemoteMediaError, fetch_public, https_url

PROVIDERS = ('alphacoders', 'motionbgs')
WORDS = {'픽셀': 'pixel', '픽셀아트': 'pixel art', '도시': 'city', '도시풍경': 'city', '야경': 'night', '도시야경': 'city',
         '자연': 'nature', '자연풍경': 'nature', '풍경': 'landscape', '숲': 'forest', '바다': 'ocean', '비': 'rain', '비오는방': 'rain',
         '애니': 'anime', '애니메이션': 'anime', '로파이': 'lofi', '노을': 'sunset', '우주': 'space', '사이버펑크': 'cyberpunk'}
VOID = {'area', 'base', 'br', 'col', 'embed', 'hr', 'img', 'input', 'link', 'meta', 'param', 'source', 'track', 'wbr'}


def clean(value, limit=200):
    return re.sub(r'\s+', ' ', str(value or '')).strip()[:limit]


def safe_site_url(value, hosts):
    try:
        parsed = https_url(value)
        return value if parsed.hostname in hosts else None
    except (ValueError, TypeError):
        return None


def page_html(url):
    return fetch_public(url, max_bytes=8*1024*1024, accept='text/html').decode('utf-8', errors='replace')


def query_words(query):
    return ' '.join(WORDS.get(word, word) for word in query.lower().split())


class AlphaImages(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.stack = []; self.records = []; self.current = None; self.root = None; self.canonical = None

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if tag == 'link' and attrs.get('rel') == 'canonical':
            self.canonical = safe_site_url(attrs.get('href'), {'alphacoders.com', 'gifs.alphacoders.com'})
        if tag not in VOID:
            self.stack.append(tag)
            if attrs.get('itemtype', '').endswith('/ImageObject'):
                if self.current is not None:
                    self.records.append(self.current)
                self.current = {}; self.root = len(self.stack)
        if self.current is not None and tag == 'meta' and attrs.get('itemprop'):
            self.current[attrs['itemprop']] = attrs.get('content') or attrs.get('href') or ''

    def handle_endtag(self, tag):
        if tag not in self.stack:
            return
        index = len(self.stack) - 1 - self.stack[::-1].index(tag)
        if self.current is not None and index < self.root:
            self.records.append(self.current); self.current = None; self.root = None
        del self.stack[index:]

    def finish(self):
        if self.current is not None:
            self.records.append(self.current)
        return self.records


def alpha_items(html):
    parser = AlphaImages(); parser.feed(html)
    items = {}
    for row in parser.finish():
        url = safe_site_url(row.get('contentUrl'), {'giffiles.alphacoders.com'})
        match = re.fullmatch(r'/\d+/([0-9]{1,12})\.gif', urlsplit(url).path) if url else None
        if not match or row.get('fileFormat', 'gif').lower() != 'gif':
            continue
        identifier = match[1]
        source = BackgroundSource(provider='alphacoders', item_id=identifier, title=clean(row.get('name')) or 'Animated wallpaper',
                                  page_url=f'https://gifs.alphacoders.com/gifs/view/{identifier}', author=clean(row.get('author'), 300))
        items[identifier] = {'id': identifier, 'title': source.title, 'url': url,
            'preview_url': safe_site_url(row.get('thumbnailUrl'), {'giffiles.alphacoders.com'}) or url,
            'width': int(row['width']) if row.get('width', '').isdigit() else None,
            'height': int(row['height']) if row.get('height', '').isdigit() else None,
            'source': source.model_dump(mode='json')}
    return list(items.values())


class MotionPage(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.items = []; self.links = []; self.image = None; self.preview = None
        self.current = None; self.title_parts = []; self.in_title = False; self.heading = []
        self.gif_url = None

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if tag == 'source' and attrs.get('type') == 'image/webp':
            self.preview = safe_site_url(urljoin('https://motionbgs.com', attrs.get('srcset', '').split(',')[0].split(' ')[0]), {'motionbgs.com'})
        if tag == 'img' and '.gif' in attrs.get('src', ''):
            self.image = safe_site_url(urljoin('https://motionbgs.com', attrs['src']), {'motionbgs.com'})
        if tag == 'a':
            href = urljoin('https://motionbgs.com', attrs.get('href', ''))
            self.links.append(href)
            if re.fullmatch(r'https://motionbgs\.com/dl/gif/[0-9]+', href):
                self.gif_url = href
            if 'gf_ttl' in attrs.get('class', '').split() and self.image:
                slug = urlsplit(href).path.strip('/')
                if re.fullmatch(r'[a-z0-9]+(?:-[a-z0-9]+)*', slug) and len(slug) <= 160:
                    self.current = {'id': slug, 'page_url': href, 'preview_url': self.preview or self.image}
                    self.title_parts = []
        if tag == 'h1':
            self.in_title = True

    def handle_data(self, data):
        if self.current is not None:
            self.title_parts.append(data)
        if self.in_title:
            self.heading.append(data)

    def handle_endtag(self, tag):
        if tag == 'h1':
            self.in_title = False
        if tag == 'a' and self.current is not None:
            title = clean(' '.join(self.title_parts)).removesuffix(' Gif Wallpaper')
            source = BackgroundSource(provider='motionbgs', item_id=self.current['id'], title=title, page_url=self.current['page_url'])
            self.items.append({'id': source.item_id, 'title': title, 'preview_url': self.current['preview_url'], 'source': source.model_dump(mode='json')})
            self.current = None; self.image = None; self.preview = None


def search(provider, query, page):
    query = query_words(query)
    if provider == 'alphacoders':
        # The search redirect drops page parameters; paginate its canonical result URL.
        try:
            html = page_html('https://alphacoders.com/search/view?' + urlencode({'q': query or 'pixel art', 'type': 'gif'}))
            if page > 1:
                parser = AlphaImages(); parser.feed(html)
                if not parser.canonical:
                    raise RemoteMediaError('제공처의 다음 검색 페이지를 찾지 못했습니다. 다른 제공처를 선택해 주세요.')
                separator = '&' if '?' in parser.canonical else '?'
                html = page_html(parser.canonical + separator + urlencode({'page': page, 'quickload': 1}))
        except RemoteMediaError as error:
            # Alpha redirects unknown terms (e.g. DEV) to a missing topic page.
            if error.status == 404:
                return {'items': [], 'page': page, 'has_more': False, 'provider': provider}
            raise
        items = alpha_items(html)
        # Fifteen tiles per page; some are MP4s and intentionally excluded.
        more = html.count('itemprop="associatedMedia"') >= 15
    else:
        words = query.split()
        categories = {'pixel', 'city', 'nature', 'forest', 'ocean', 'rain', 'anime', 'lofi', 'landscape', 'sunset', 'space', 'cyberpunk', 'night', 'winter', 'sakura'}
        category = next((word for word in words if word in categories), re.sub(r'[^a-z0-9-]', '-', query).strip('-')) or 'pixel'
        base = f'https://motionbgs.com/gifs:{quote(category)}/'
        try:
            html = page_html(base + (f'{page}/' if page > 1 else ''))
        except RemoteMediaError as error:
            if error.status == 404:
                return {'items': [], 'page': page, 'has_more': False, 'provider': provider}
            raise
        parser = MotionPage(); parser.feed(html)
        items = parser.items
        more = base + f'{page+1}/' in parser.links
    return {'items': [{key: value for key, value in item.items() if key != 'url'} for item in items],
            'page': page, 'has_more': more and page < 20, 'provider': provider}


def resolve(provider, identifier):
    if provider == 'alphacoders':
        if not re.fullmatch(r'[0-9]{1,12}', identifier):
            raise RemoteMediaError('GIF 항목 번호가 올바르지 않습니다.', 422)
        items = alpha_items(page_html(f'https://gifs.alphacoders.com/gifs/view/{identifier}'))
        item = next((item for item in items if item['id'] == identifier), None)
        if not item:
            raise RemoteMediaError('다운로드할 수 있는 GIF를 찾지 못했습니다.', 422)
        return item
    if not re.fullmatch(r'[a-z0-9]+(?:-[a-z0-9]+)*', identifier) or len(identifier) > 160:
        raise RemoteMediaError('GIF 항목 번호가 올바르지 않습니다.', 422)
    url = f'https://motionbgs.com/{identifier}'
    parser = MotionPage(); parser.feed(page_html(url))
    if not parser.gif_url:
        raise RemoteMediaError('이 배경은 GIF 다운로드를 제공하지 않습니다.', 422)
    title = clean(' '.join(parser.heading)).removesuffix(' Live Wallpaper') or identifier.replace('-', ' ')
    source = BackgroundSource(provider='motionbgs', item_id=identifier, title=title, page_url=url)
    return {'url': parser.gif_url, 'title': title, 'source': source.model_dump(mode='json')}
