import asyncio
import unittest
from unittest.mock import patch

import httpx
from fastapi import HTTPException
from fastapi.testclient import TestClient
from pydantic import ValidationError

import test_auth as legacy_tests
from test_auth import HEADERS
from app.core.security import cipher
from app.db.models import ProxySource, SharedLink
from app.db.session import SessionLocal
from app.main import app
from app.schemas.proxy import CustomAPI, PreviewData
from app.services.proxy import fetch_hosts, normalize_hosts
from app.services import weather


class CustomAPIAdapters(unittest.TestCase):
    def fetch(self, config, handler):
        original = httpx.Client
        source = ProxySource(provider='custom', base_url='https://inventory.test/prefix',
                             custom_api=CustomAPI(**config).model_dump(), verify_tls=True,
                             token_encrypted=cipher().encrypt(b'private-test-key').decode())
        with patch('app.services.proxy.httpx.Client', side_effect=lambda **kw: original(transport=httpx.MockTransport(handler), **kw)):
            return fetch_hosts(source)

    def test_custom_json_path_header_and_normalization(self):
        config = CustomAPI(endpoint='/api/links?limit=50', items_path='data.items', url_field='target.urls', name_field='title', auth_type='header').model_dump()
        def handler(request):
            self.assertEqual(str(request.url), 'https://inventory.test/prefix/api/links?limit=50')
            self.assertEqual(request.headers['X-API-Key'], 'private-test-key')
            self.assertNotIn('Authorization', request.headers)
            return httpx.Response(200, json={'data': {'items': [{'title': 'My App', 'target': {'urls': ['https://app.test/path', 'javascript:alert(1)', 'https://app.test/path', 'https://user:password@app.test']}}]}})
        hosts = self.fetch(config, handler)
        entries, skipped = normalize_hosts('custom', hosts, PreviewData(), config)
        self.assertEqual(entries, [{'id': '0', 'name': 'My App', 'url': 'https://app.test/path'}])
        self.assertEqual(skipped, 3)

    def test_string_array_domain_format_and_no_auth(self):
        config = CustomAPI(endpoint='links', url_field='', name_field='', auth_type='none', url_format='domain').model_dump()
        def handler(request):
            self.assertNotIn('Authorization', request.headers)
            return httpx.Response(200, json=['one.test', '*.test', 'two.test'])
        entries, skipped = normalize_hosts('custom', self.fetch(config, handler), PreviewData(scheme='http', public_port=8085), config)
        self.assertEqual([row['url'] for row in entries], ['http://one.test:8085/', 'http://two.test:8085/'])
        self.assertEqual(skipped, 1)

    def test_invalid_config_and_wrong_response(self):
        for endpoint in ('https://other.test/api', '//other.test/api', '../links', '%2e%2e/links', '/api#fragment', '/', 'api\nlinks'):
            with self.assertRaises(ValidationError, msg=endpoint):
                CustomAPI(endpoint=endpoint)
        for header in ('Host', 'Cookie', 'X-API\r\nKey'):
            with self.assertRaises(ValidationError):
                CustomAPI(endpoint='links', auth_header=header)
        for data in ({'data': {}}, {'items': []}, ['valid', 123]):
            with self.assertRaises(HTTPException):
                self.fetch({'endpoint': 'links', 'items_path': 'data'}, lambda request: httpx.Response(200, json=data))
        with self.assertRaises(HTTPException):
            self.fetch({'endpoint': 'links'}, lambda request: httpx.Response(302, headers={'Location': 'https://other.test'}))


class CustomAPIRoutes(unittest.TestCase):
    setUp = legacy_tests.AuthenticationTests.setUp
    tearDown = legacy_tests.AuthenticationTests.tearDown
    setup_owner = legacy_tests.AuthenticationTests.setup_owner

    def test_custom_save_secret_preservation_and_auth_change(self):
        self.setup_owner()
        payload = {'name': 'My Inventory', 'provider': 'custom', 'base_url': 'https://inventory.test', 'token': 'private-test-key', 'custom_api': {'endpoint': 'links'}}
        result = self.client.post('/api/admin/proxy-sources', json=payload, headers=HEADERS)
        self.assertEqual(result.status_code, 200, result.text)
        source = result.json()
        self.assertNotIn('private-test-key', result.text)
        self.assertEqual(source['custom_api']['endpoint'], 'links')
        path = '/api/admin/proxy-sources/'+source['id']
        self.assertEqual(self.client.put(path, json=payload | {'token': None}, headers=HEADERS).status_code, 200)
        with patch('app.api.proxy.fetch_hosts', return_value=[{'name': 'App', 'url': 'https://app.test'}]):
            result = self.client.post(path+'/preview', json={}, headers=HEADERS)
        self.assertEqual(result.status_code, 200, result.text)
        self.assertEqual(result.json()['entries'][0]['name'], 'App')
        no_auth = payload | {'token': None, 'custom_api': {'endpoint': 'links', 'auth_type': 'none'}}
        self.assertFalse(self.client.put(path, json=no_auth, headers=HEADERS).json()['has_token'])
        self.assertEqual(self.client.put(path, json=payload | {'token': None}, headers=HEADERS).status_code, 422)
        with SessionLocal() as db:
            self.assertEqual(db.get(ProxySource, source['id']).token_encrypted, '')
        self.assertEqual(self.client.post('/api/admin/proxy-sources', json=payload | {'custom_api': None}, headers=HEADERS).status_code, 422)

    def test_bulk_library_atomic_revocation_ownership_and_duplicates(self):
        self.setup_owner()
        self.client.post('/api/admin/users', json={'username': 'member', 'password': 'a-member-password'}, headers=HEADERS)
        member = TestClient(app)
        member.post('/api/auth/login', json={'username': 'member', 'password': 'a-member-password'}, headers=HEADERS)
        category = member.get('/api/portal').json()['tabs'][0]['categories'][0]['id']
        other_category = self.client.get('/api/portal').json()['tabs'][0]['categories'][0]['id']
        with SessionLocal.begin() as db:
            links = [SharedLink(name=f'Link {i}', url=f'https://app{i}.test/', source_name='Fixture', published=i < 2) for i in range(3)]
            db.add_all(links); db.flush()
            ids = [link.id for link in links]
        payload = {'category_id': category, 'link_ids': ids[:2]}
        self.assertEqual(TestClient(app).post('/api/library/add', json=payload, headers=HEADERS).status_code, 401)
        self.assertEqual(member.post('/api/library/add', json=payload).status_code, 403)
        self.assertEqual(member.post('/api/library/add', json=payload | {'category_id': other_category}, headers=HEADERS).status_code, 404)
        self.assertEqual(member.post('/api/library/add', json=payload | {'link_ids': ids}, headers=HEADERS).status_code, 409)
        self.assertFalse(any(link['added'] for link in member.get('/api/library').json()))
        result = member.post('/api/library/add', json=payload, headers=HEADERS)
        self.assertEqual(result.status_code, 200, result.text)
        self.assertEqual(result.json(), {'added': 2, 'duplicates': 0})
        self.assertEqual(member.post('/api/library/add', json=payload, headers=HEADERS).json(), {'added': 0, 'duplicates': 2})

    def test_weather_requires_login_and_uses_saved_settings(self):
        self.assertEqual(self.client.get('/api/weather').status_code, 401)
        self.setup_owner()
        response = self.client.put('/api/admin/settings', json={'search_engine': 'g', 'timezone': 'Asia/Seoul', 'weather_location': 'Seoul', 'temperature_scale': 'F'}, headers=HEADERS)
        self.assertEqual(response.status_code, 200, response.text)
        with patch('app.api.weather.current_weather', return_value={'available': True, 'temperature': 19.5}) as mocked:
            self.assertEqual(self.client.get('/api/weather').json()['temperature'], 19.5)
            mocked.assert_awaited_once_with('Seoul', 'F')


class WeatherTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        weather.cache.clear(); weather.locations.clear()
        weather.lock = asyncio.Lock()

    async def test_live_shape_units_cache_and_fixed_urls(self):
        calls = []
        def handler(request):
            calls.append(request)
            if request.url.host == 'geocoding-api.open-meteo.com':
                self.assertEqual(request.url.params['name'], '서울')
                return httpx.Response(200, json={'results': [{'name': '서울', 'country': '대한민국', 'latitude': 37.57, 'longitude': 126.98}]})
            self.assertEqual(request.url.host, 'api.open-meteo.com')
            self.assertEqual(request.url.params['current'], 'temperature_2m')
            self.assertEqual(request.url.params['temperature_unit'], 'fahrenheit')
            return httpx.Response(200, json={'current': {'temperature_2m': 68.0, 'time': '2026-10-20T16:15'}})
        original = httpx.AsyncClient
        with patch('app.services.weather.httpx.AsyncClient', side_effect=lambda **kw: original(transport=httpx.MockTransport(handler), **kw)):
            result = await weather.current_weather('서울', 'F')
            self.assertTrue(result['available'])
            self.assertEqual(result['temperature'], 68.0)
            self.assertEqual(await weather.current_weather('서울', 'F'), result)
        self.assertEqual(len(calls), 2)

    async def test_unavailable_invalid_location_and_negative_cache(self):
        with patch('app.services.weather.fetch_weather', side_effect=httpx.ConnectError('private details')) as mocked:
            for _ in range(2):
                result = await weather.current_weather('Unknown', 'C')
                self.assertFalse(result['available'])
                self.assertNotIn('private details', str(result))
            self.assertEqual(mocked.await_count, 2)
        original = httpx.AsyncClient
        with patch('app.services.weather.httpx.AsyncClient', side_effect=lambda **kw: original(transport=httpx.MockTransport(lambda request: httpx.Response(200, json={'results': []})), **kw)):
            self.assertIn('위치를 찾지', (await weather.current_weather('No City', 'C'))['message'])

    async def test_transient_timeout_retries_once(self):
        with patch('app.services.weather.fetch_weather', side_effect=[httpx.ReadTimeout('timeout'), {'available': True, 'temperature': 20}]) as mocked:
            self.assertTrue((await weather.current_weather('Seoul', 'C'))['available'])
            self.assertEqual(mocked.await_count, 2)
