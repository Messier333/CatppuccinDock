"""Official video search; selected clips are converted to local GIF backgrounds."""
import hashlib
import json
import re
import time
from urllib.parse import urlencode, urlsplit

from fastapi import HTTPException
from sqlalchemy import select

from app.db.models import Setting
from app.db.session import SessionLocal
from app.schemas.backgrounds import BackgroundSource
from app.services.media.media_policy import provider_key
from app.services.media.remote_media import RemoteMediaError, fetch_public
from app.services.media.wallpaper_gifs import clean, query_words, safe_site_url


def request(params):
    key=provider_key('pixabay')
    if not key:
        raise HTTPException(409,'관리자 설정의 GIF · 배경 관리에서 Pixabay API 키를 등록해 주세요.')
    cache_key='pixabay-search:'+hashlib.sha256((key+json.dumps(params,sort_keys=True)).encode()).hexdigest()[:40]
    with SessionLocal() as db:
        row=db.get(Setting,cache_key)
        if row and row.value['expires']>time.time():
            return row.value['data']
    url='https://pixabay.com/api/videos/?'+urlencode(params|{'key':key,'safesearch':'true','per_page':24})
    result=json.loads(fetch_public(url,max_bytes=2*1024*1024,accept='application/json'))
    if not isinstance(result,dict) or not isinstance(result.get('hits'),list):
        raise RemoteMediaError('Pixabay 검색 응답을 읽지 못했습니다.')
    # The official API requires response caching for 24 hours, including restarts.
    with SessionLocal.begin() as db:
        rows=list(db.scalars(select(Setting).where(Setting.key.like('pixabay-search:%'))))
        for row in sorted(rows,key=lambda row:row.value.get('expires',0))[:max(0,len(rows)-255)]:
            db.delete(row)
        row=db.get(Setting,cache_key)
        value={'expires':time.time()+86400,'data':result}
        if row:row.value=value
        else:db.add(Setting(key=cache_key,value=value))
    return result


def item(row):
    identifier=str(row.get('id',''))
    if not re.fullmatch(r'[0-9]{1,12}',identifier):return None
    variants=row.get('videos') or {}
    variant=next((variants[name] for name in ('tiny','small','medium') if variants.get(name,{}).get('url')),None)
    if not variant:return None
    url=safe_site_url(variant['url'],{'cdn.pixabay.com'})
    thumbnail=safe_site_url(variant.get('thumbnail'),{'cdn.pixabay.com'})
    if not url or not urlsplit(url).path.endswith('.mp4') or not thumbnail:return None
    source=BackgroundSource(provider='pixabay',item_id=identifier,title=clean(row.get('tags')) or 'Video background',
        page_url=f'https://pixabay.com/videos/id-{identifier}/',author=clean(row.get('user'),300),
        license='Pixabay Content License',license_url='https://pixabay.com/service/license-summary/')
    return {'id':identifier,'title':source.title,'url':url,'preview_url':thumbnail,'width':variant.get('width'),
            'height':variant.get('height'),'media_type':'video','duration':row.get('duration'),
            'source':source.model_dump(mode='json')}


def search(query,page):
    q=query_words(query)
    result=request({'q':q,'page':page,'lang':'ko' if re.search('[가-힣]',q) else 'en'})
    items=[item(row) for row in result['hits']]
    return {'items':[{key:value for key,value in row.items() if key!='url'} for row in items if row],
            'page':page,'has_more':page*24<min(500,result.get('totalHits',0)) and page<20,'provider':'pixabay'}


def resolve(identifier):
    if not re.fullmatch(r'[0-9]{1,12}',identifier):
        raise HTTPException(422,'영상 항목 번호가 올바르지 않습니다.')
    result=request({'id':identifier})
    row=next((item(row) for row in result['hits'] if str(row.get('id'))==identifier),None)
    if not row:raise HTTPException(422,'가져올 수 있는 영상을 찾지 못했습니다.')
    return row
