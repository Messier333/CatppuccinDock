"""Current temperature from fixed Open-Meteo endpoints; no API key required."""
import asyncio
import json
import math
import time
from collections import OrderedDict

import httpx


cache = OrderedDict()
locations = OrderedDict()
lock = asyncio.Lock()


async def read_json(client, url, params):
    async with client.stream('GET', url, params=params) as response:
        response.raise_for_status()
        body = bytearray()
        async for chunk in response.aiter_bytes():
            body.extend(chunk)
            if len(body) > 131072:
                raise ValueError('Weather response too large')
    return json.loads(body)


async def fetch_weather(location, scale):
    async with httpx.AsyncClient(timeout=httpx.Timeout(6, connect=3), follow_redirects=False, trust_env=False) as client:
        if location in locations and locations[location][0] > time.monotonic():
            place = locations[location][1]
        else:
            geo = await read_json(client, 'https://geocoding-api.open-meteo.com/v1/search',
                                  {'name': location, 'count': 1, 'language': 'ko', 'format': 'json'})
            results = geo.get('results', [])
            if not isinstance(results, list) or not results:
                return {'available': False, 'message': '위치를 찾지 못했어요. 설정에서 도시명을 확인해 주세요.'}
            place = results[0]
            latitude, longitude = place['latitude'], place['longitude']
            if not isinstance(latitude, (float, int)) or not -90 <= latitude <= 90 or not isinstance(longitude, (float, int)) or not -180 <= longitude <= 180:
                raise ValueError('Invalid weather coordinates')
            locations[location] = (time.monotonic()+86400, place)
            while len(locations) > 64:
                locations.popitem(last=False)
        data = await read_json(client, 'https://api.open-meteo.com/v1/forecast',
                               {'latitude': place['latitude'], 'longitude': place['longitude'],
                                'current': 'temperature_2m', 'temperature_unit': 'fahrenheit' if scale == 'F' else 'celsius',
                                'timezone': 'auto', 'forecast_days': 1})
        current = data['current']
        temperature = current['temperature_2m']
        if isinstance(temperature, bool) or not isinstance(temperature, (int, float)) or not math.isfinite(temperature):
            raise ValueError('Invalid temperature')
        return {'available': True, 'temperature': temperature, 'observed_at': current.get('time'),
                'resolved_location': ', '.join(str(value) for value in (place.get('name'), place.get('country')) if value)}


async def fetch_with_retry(location, scale):
    try:
        return await fetch_weather(location, scale)
    except (httpx.ConnectError, httpx.TimeoutException):
        return await fetch_weather(location, scale)


async def current_weather(location, scale, force=False):
    key = (location, scale)
    async with lock:
        now = time.monotonic()
        if key in cache:
            expiry, saved = cache[key]
            # A manual refresh bypasses the ten minute cache, at most once a minute.
            created = expiry - (600 if saved['available'] else 60)
            if expiry > now and (not force or now - created < 60):
                return saved
        try:
            result = await asyncio.wait_for(fetch_with_retry(location, scale), timeout=15)
        except (httpx.HTTPError, ValueError, KeyError, TypeError, AttributeError, asyncio.TimeoutError):
            result = {'available': False, 'message': '날씨 서비스에 연결하지 못했어요. 잠시 후 다시 시도해 주세요.'}
        result = result | {'location': location, 'scale': scale, 'provider': 'Open-Meteo'}
        cache[key] = (now+(600 if result['available'] else 60), result)
        while len(cache) > 64:
            cache.popitem(last=False)
        return result
