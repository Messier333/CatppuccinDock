"""GIFDB's public full-text search and verified GIF detail pages."""
from html.parser import HTMLParser
import re
from urllib.parse import quote, urljoin, urlsplit

from app.schemas.backgrounds import BackgroundSource
from app.services.media.remote_media import RemoteMediaError
from app.services.media.wallpaper_gifs import clean, page_html, query_words, safe_site_url

SLUG = r'[a-z0-9]+(?:-[a-z0-9]+)*'


class GifPage(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.current = None; self.items = {}; self.links = []; self.meta = {}

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if tag == 'meta' and attrs.get('property'):
            self.meta[attrs['property']] = attrs.get('content','')
        if tag == 'a':
            href = urljoin('https://gifdb.com',attrs.get('href',''))
            self.links.append(href)
            match = re.fullmatch(r'/gif/('+SLUG+r')\.html',urlsplit(href).path)
            self.current = match[1] if match and urlsplit(href).hostname=='gifdb.com' and len(match[1])<=160 else None
        if tag == 'img' and self.current:
            url = safe_site_url(urljoin('https://gifdb.com',attrs.get('src') or attrs.get('data-src') or ''), {'gifdb.com'})
            if not url or not urlsplit(url).path.startswith('/images/'):
                return
            title = clean(attrs.get('alt')).removesuffix(' GIF') or self.current.replace('-',' ')
            source = BackgroundSource(provider='gifdb',item_id=self.current,title=title,page_url=f'https://gifdb.com/gif/{self.current}.html')
            self.items[self.current] = {'id':self.current,'title':title,'preview_url':url,'source':source.model_dump(mode='json')}

    def handle_endtag(self, tag):
        if tag == 'a':
            self.current = None


def search(query,page):
    url = 'https://gifdb.com/search/'+quote(query_words(query),safe='')
    try:
        html = page_html(url+(f'?page={page}' if page>1 else ''))
    except RemoteMediaError as error:
        if error.status==404:
            return {'items':[],'page':page,'has_more':False,'provider':'gifdb'}
        raise
    parser=GifPage();parser.feed(html)
    words=set(re.findall(r'[a-z0-9]+',query_words(query)))
    def relevance(item):
        title=re.findall(r'[a-z0-9]+',item['title'].lower())
        return sum(any(token.startswith(word) for token in title) for word in words)
    # Public full-text pages sometimes include unrelated trending uploads.
    items=sorted((item for item in parser.items.values() if not words or relevance(item)),key=relevance,reverse=True)
    more=any(urlsplit(link).query==f'page={page+1}' and urlsplit(link).path.rstrip('/')==urlsplit(url).path.rstrip('/') for link in parser.links)
    return {'items':items,'page':page,'has_more':more and page<20,'provider':'gifdb'}


def resolve(identifier):
    if len(identifier)>160 or not re.fullmatch(SLUG,identifier):
        raise RemoteMediaError('GIF 항목 번호가 올바르지 않습니다.',422)
    url=f'https://gifdb.com/gif/{identifier}.html'
    try:
        html=page_html(url)
    except (TimeoutError,ConnectionError):
        html=page_html(url)
    parser=GifPage();parser.feed(html)
    media=safe_site_url(parser.meta.get('og:image'),{'gifdb.com'})
    if not media or not re.fullmatch(r'/images/(?:high|branded/high)/'+re.escape(identifier)+r'\.gif',urlsplit(media).path):
        raise RemoteMediaError('원본 GIF 다운로드 주소를 찾지 못했습니다.',422)
    title=clean(parser.meta.get('og:title')).removesuffix(' | GIFDB.com').removesuffix(' GIF') or identifier.replace('-',' ')
    source=BackgroundSource(provider='gifdb',item_id=identifier,title=title,page_url=url)
    return {'url':media,'title':title,'source':source.model_dump(mode='json')}
