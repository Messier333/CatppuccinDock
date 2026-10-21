"""Public GIF search and verified imports; provider IDs never become arbitrary URLs."""
from collections import OrderedDict
from concurrent.futures import ThreadPoolExecutor
from html.parser import HTMLParser
import http.client
import json
import re
import time
from threading import BoundedSemaphore, Lock
from urllib.parse import urlencode, quote
from uuid import UUID

from fastapi import HTTPException

from app.schemas.backgrounds import BackgroundSource
from app.services.media.backgrounds import MAX_INPUT_BYTES
from app.services.media.remote_media import RemoteMediaError, fetch_public, https_url
from app.services.media import wallpaper_gifs
from app.services.media import gifdb, pixabay_gifs
from app.services.media.media_policy import provider_key

PROVIDERS = {'gifdb':'GIFDB','pixabay':'Pixabay','alphacoders': 'Alpha Coders', 'motionbgs': 'MotionBgs', 'commons': 'Wikimedia Commons', 'openverse': 'Openverse'}
PAGE_SIZE = 12
slots = BoundedSemaphore(3)
download_slots = BoundedSemaphore(1)
aggregate_slots = BoundedSemaphore(2)
search_pool = ThreadPoolExecutor(max_workers=3,thread_name_prefix='gif-search')
lock = Lock()
cache = OrderedDict()
budgets = OrderedDict()
budget_clock = time.monotonic


class PlainText(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.parts = []

    def handle_data(self, data):
        self.parts.append(data)


def plain(value, limit):
    parser = PlainText()
    parser.feed(str(value or '')[:10000])
    return re.sub(r'\s+', ' ', ' '.join(parser.parts)).strip()[:limit]


def check_budget(user_id, action):
    bucket = int(budget_clock() // 60)
    key = (user_id, action)
    with lock:
        previous, count = budgets.pop(key, (bucket, 0))
        count = count + 1 if previous == bucket else 1
        budgets[key] = (bucket, count)
        while len(budgets) > 1024:
            budgets.popitem(last=False)
        if count > (20 if action == 'search' else 6):
            raise HTTPException(429, 'GIF 요청이 많습니다. 잠시 후 다시 시도해 주세요.')


def provider_json(url, params=None):
    raw = fetch_public(url + ('?' + urlencode(params) if params else ''), max_bytes=2*1024*1024, accept='application/json')
    result = json.loads(raw)
    if not isinstance(result, dict) or result.get('error'):
        raise RemoteMediaError('GIF 검색 서비스가 올바른 결과를 반환하지 않았습니다.')
    return result


def usable_url(value):
    try:
        https_url(value)
        return value
    except (RemoteMediaError, AttributeError):
        return None


def commons_item(row):
    info = (row.get('imageinfo') or [{}])[0]
    url = usable_url(info.get('url'))
    if info.get('mime') != 'image/gif' or not url or info.get('size', 0) > MAX_INPUT_BYTES:
        return None
    meta = info.get('extmetadata') or {}
    source = BackgroundSource(provider='commons', item_id=str(row['pageid']), title=plain(row.get('title', '').removeprefix('File:'), 200),
        page_url=f"https://commons.wikimedia.org/?curid={row['pageid']}", author=plain(meta.get('Artist', {}).get('value'), 300),
        license=plain(meta.get('LicenseShortName', {}).get('value'), 80), license_url=usable_url(meta.get('LicenseUrl', {}).get('value')))
    return {'id': source.item_id, 'title': source.title, 'url': url, 'preview_url': usable_url(info.get('thumburl')) or url,
            'source': source.model_dump(mode='json'), 'width': info.get('width'), 'height': info.get('height')}


def openverse_item(row):
    url = usable_url(row.get('url'))
    if row.get('filetype', '').lower() != 'gif' or not url or (row.get('filesize') or 0) > MAX_INPUT_BYTES:
        return None
    page_url = usable_url(row.get('foreign_landing_url'))
    if not page_url:
        return None
    source = BackgroundSource(provider='openverse', item_id=str(UUID(row['id'])), title=plain(row.get('title'), 200),
        page_url=page_url, author=plain(row.get('creator'), 300), license=plain(f"{row.get('license', '')} {row.get('license_version', '')}", 80),
        license_url=usable_url(row.get('license_url')))
    return {'id': source.item_id, 'title': source.title, 'url': url, 'preview_url': usable_url(row.get('thumbnail')) or url,
            'source': source.model_dump(mode='json'), 'width': row.get('width'), 'height': row.get('height')}


def commons_params():
    return {'action': 'query', 'format': 'json', 'formatversion': 2, 'prop': 'imageinfo', 'iiprop': 'url|mime|size|extmetadata',
            'iiurlwidth': 240, 'iiextmetadatafilter': 'Artist|LicenseShortName|LicenseUrl'}


def search(provider, query, page):
    if provider=='pixabay' and not provider_key('pixabay'):
        raise HTTPException(409,'관리자 설정의 GIF · 배경 관리에서 Pixabay API 키를 등록해 주세요.')
    if provider=='all':
        if not aggregate_slots.acquire(blocking=False):
            raise HTTPException(503,'GIF 통합 검색이 진행 중입니다. 잠시 후 다시 시도해 주세요.')
        try:
            providers=['gifdb','alphacoders','motionbgs']
            if provider_key('pixabay'):providers.append('pixabay')
            futures=[(name,search_pool.submit(search,name,query,page)) for name in providers]
            results=[];unavailable=[]
            for name,future in futures:
                try:results.append(future.result())
                except (HTTPException,*NETWORK_ERRORS):unavailable.append(PROVIDERS[name])
            if not results:raise HTTPException(502,'GIF 제공처에 연결하지 못했습니다. 잠시 후 다시 시도해 주세요.')
            items=[result['items'][index] for index in range(max(len(result['items']) for result in results)) for result in results if index<len(result['items'])]
            return {'items':items, 'page':page,
                    'has_more':any(result['has_more'] for result in results),'provider':'all','unavailable':unavailable}
        finally:aggregate_slots.release()
    key = (provider, query, page)
    with lock:
        saved = cache.get(key)
        if saved and saved[0] > time.monotonic():
            cache.move_to_end(key)
            return saved[1]
    if not slots.acquire(blocking=False):
        raise HTTPException(503, 'GIF 검색이 진행 중입니다. 잠시 후 다시 시도해 주세요.')
    try:
        if provider in ('gifdb','pixabay'):
            result=gifdb.search(query,page) if provider=='gifdb' else pixabay_gifs.search(query,page)
            with lock:
                cache[key]=(time.monotonic()+120,result);cache.move_to_end(key)
                while len(cache)>128:cache.popitem(last=False)
            return result
        if provider in wallpaper_gifs.PROVIDERS:
            result = wallpaper_gifs.search(provider, query, page)
            with lock:
                cache[key] = (time.monotonic()+120, result)
                cache.move_to_end(key)
                while len(cache) > 128:
                    cache.popitem(last=False)
            return result
        if provider == 'commons':
            result = provider_json('https://commons.wikimedia.org/w/api.php', commons_params() | {
                'generator': 'search', 'gsrsearch': f'{query} filemime:image/gif', 'gsrnamespace': 6,
                'gsrlimit': PAGE_SIZE, 'gsroffset': (page-1)*PAGE_SIZE})
            rows = sorted(result.get('query', {}).get('pages', []), key=lambda row: row.get('index', 0))
            items = [commons_item(row) for row in rows]
            more = 'continue' in result
        else:
            result = provider_json('https://api.openverse.org/v1/images/', {'q': query, 'extension': 'gif', 'page_size': PAGE_SIZE, 'page': page})
            items = [openverse_item(row) for row in result.get('results', [])]
            more = page < result.get('page_count', page)
        # Downloads are resolved again from provider IDs, rather than trusting client URLs.
        result = {'items': [{key: value for key, value in item.items() if key != 'url'} for item in items if item],
                  'page': page, 'has_more': more and page < 20, 'provider': provider}
        with lock:
            cache[key] = (time.monotonic()+120, result)
            cache.move_to_end(key)
            while len(cache) > 128:
                cache.popitem(last=False)
        return result
    finally:
        slots.release()


def download(provider, item_id, *, max_bytes=MAX_INPUT_BYTES, on_chunk=None):
    if not download_slots.acquire(blocking=False):
        raise HTTPException(503, 'GIF 다운로드가 진행 중입니다. 잠시 후 다시 시도해 주세요.')
    try:
        options = {'on_chunk': on_chunk} if on_chunk else {}
        if provider in ('gifdb','pixabay'):
            item=gifdb.resolve(item_id) if provider=='gifdb' else pixabay_gifs.resolve(item_id)
            data=fetch_public(item['url'],max_bytes=max_bytes,accept='video/mp4' if provider=='pixabay' else 'image/gif',timeout=60,**options)
            return data,item['title'],item['source']
        if provider in wallpaper_gifs.PROVIDERS:
            item = wallpaper_gifs.resolve(provider, item_id)
            data = fetch_public(item['url'], max_bytes=max_bytes, accept='image/gif', timeout=60, **options)
            return data, item['title'], item['source']
        if provider == 'commons':
            if not item_id.isdecimal() or len(item_id) > 12:
                raise HTTPException(422, 'GIF 항목 번호가 올바르지 않습니다.')
            result = provider_json('https://commons.wikimedia.org/w/api.php', commons_params() | {'pageids': item_id})
            rows = result.get('query', {}).get('pages', [])
            item = commons_item(rows[0]) if rows else None
        else:
            try:
                identifier = str(UUID(item_id))
            except ValueError as error:
                raise HTTPException(422, 'GIF 항목 번호가 올바르지 않습니다.') from error
            item = openverse_item(provider_json(f'https://api.openverse.org/v1/images/{quote(identifier)}/'))
        if not item:
            raise HTTPException(422, '가져올 수 있는 100MB 이하의 GIF가 아닙니다. 다른 항목을 선택해 주세요.')
        data = fetch_public(item['url'], max_bytes=max_bytes, accept='image/gif', timeout=60, **options)
        return data, item['title'] or 'GIF 배경', item['source']
    finally:
        download_slots.release()


def public_error(error):
    if isinstance(error, RemoteMediaError):
        return HTTPException(error.status, str(error))
    if isinstance(error, TimeoutError):
        return HTTPException(504, 'GIF 서비스 응답 시간이 초과되었습니다. 다른 제공처를 선택하거나 다시 시도해 주세요.')
    return HTTPException(502, 'GIF 서비스에 연결하지 못했습니다. 다른 제공처를 선택하거나 직접 업로드해 주세요.')


NETWORK_ERRORS = (OSError, ValueError, TypeError, KeyError, http.client.HTTPException)
