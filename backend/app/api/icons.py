import hashlib

from fastapi import APIRouter, Depends, Query
from fastapi.responses import Response

from app.api.dependencies import require_user
from app.services.icons import COLLECTIONS, KEYWORDS, collection_data, svg_for


router = APIRouter(prefix='/api/icons', dependencies=[Depends(require_user)])


@router.get('/collections')
def collections():
    return [{'id': prefix, 'name': name, 'total': len(collection_data(prefix)['icons']),
             'license': collection_data(prefix)['info']['license']} for prefix, name in COLLECTIONS.items()]


@router.get('')
def search(collection: str = 'tabler', q: str = Query(default='', max_length=80), offset: int = Query(default=0, ge=0)):
    data = collection_data(collection)
    terms = [KEYWORDS.get(word, word) for word in q.lower().split()]
    names = sorted(name for name in data['icons'] if all(term in name for term in terms))
    return {'icons': [collection+':'+name for name in names[offset:offset+48]], 'total': len(names), 'offset': offset, 'has_more': offset+48 < len(names)}


@router.get('/{name}.svg')
def icon(name: str):
    svg = svg_for(name)
    return Response(svg, media_type='image/svg+xml', headers={
        'Cache-Control': 'private, max-age=86400', 'ETag': '"'+hashlib.sha256(svg.encode()).hexdigest()+'"',
        'Content-Security-Policy': "default-src 'none'; style-src 'none'; sandbox", 'X-Content-Type-Options': 'nosniff'})
