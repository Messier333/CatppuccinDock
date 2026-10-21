import asyncio
import ipaddress
import re
import time
from collections import OrderedDict, defaultdict, deque
from typing import Literal

import httpx
from fastapi import APIRouter, Depends
from pydantic import BaseModel, ConfigDict, Field

from app.api.dependencies import require_mutation_header, require_user
from app.db.models import User


router = APIRouter(prefix='/api/search')
attempts = defaultdict(deque)
cache = OrderedDict()


class SuggestData(BaseModel):
    model_config = ConfigDict(extra='forbid')
    query: str = Field(min_length=1, max_length=120)
    provider: Literal['g', 'd', 'y'] = 'g'


def can_suggest(value):
    if len(value) < 2 or any(char in value for char in '/\\:@?#') or re.search(r'[\x00-\x1f\x7f]', value):
        return False
    # Internal hostnames, domains and IP addresses stay local to bookmark search.
    if '.' in value or value.lower().startswith('localhost'):
        return False
    try:
        ipaddress.ip_address(value)
        return False
    except ValueError:
        return True


async def google_suggestions(query):
    return await provider_suggestions(query, 'g')


async def provider_suggestions(query, provider):
    url, params = {
        'g': ('https://suggestqueries.google.com/complete/search', {'client': 'firefox', 'hl': 'ko', 'q': query}),
        'd': ('https://duckduckgo.com/ac/', {'q': query, 'type': 'list'}),
        'y': ('https://suggest.yandex.com/suggest-ff.cgi', {'part': query, 'uil': 'en'}),
    }[provider]
    try:
        async with httpx.AsyncClient(timeout=httpx.Timeout(2.5, connect=1.5), follow_redirects=False, trust_env=False) as client:
            async with client.stream('GET', url, params=params,
                                     headers={'Accept': 'application/json'}) as response:
                if response.status_code != 200:
                    return None
                body = bytearray()
                async for chunk in response.aiter_bytes():
                    body.extend(chunk)
                    if len(body) > 65536:
                        return None
                import json
                data = json.loads(body)
                if not isinstance(data, list) or len(data) < 2 or not isinstance(data[1], list):
                    return None
                return list(dict.fromkeys(item for item in data[1] if isinstance(item, str) and 1 <= len(item) <= 200 and can_suggest(item)))[:6]
    except (httpx.HTTPError, ValueError, UnicodeError):
        return None


@router.post('/suggestions', dependencies=[Depends(require_mutation_header)])
async def suggestions(payload: SuggestData, user: User = Depends(require_user)):
    query = payload.query.strip()
    if not can_suggest(query):
        return {'suggestions': [], 'available': True}
    now = time.monotonic()
    # Queries are transient, scoped to this user, and never written to access URLs.
    key = (user.id, payload.provider, query)
    if key in cache and cache[key][0] > now:
        return cache[key][1]
    if len(attempts) > 512:
        for user_id in list(attempts):
            if not attempts[user_id] or attempts[user_id][-1] < now-60:
                del attempts[user_id]
    recent = attempts[user.id]
    while recent and recent[0] < now-60:
        recent.popleft()
    if len(recent) >= 60:
        return {'suggestions': [], 'available': False}
    recent.append(now)
    try:
        result = await asyncio.wait_for(google_suggestions(query) if payload.provider == 'g' else provider_suggestions(query, payload.provider), timeout=3)
    except asyncio.TimeoutError:
        result = None
    response = {'suggestions': result or [], 'available': result is not None}
    cache[key] = (now+(60 if result is not None else 10), response)
    cache.move_to_end(key)
    while len(cache) > 256:
        cache.popitem(last=False)
    return response
