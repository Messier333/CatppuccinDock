import unittest
from unittest.mock import AsyncMock, patch

import httpx
from sqlalchemy import select
import test_auth as legacy_tests
from test_auth import HEADERS
from app.api import search
from app.db.migrations import migrate
from app.db.models import Migration, Setting
from app.db.session import SessionLocal


class ClockProviderRoutes(unittest.TestCase):
    tearDown = legacy_tests.AuthenticationTests.tearDown
    setup_owner = legacy_tests.AuthenticationTests.setup_owner

    def setUp(self):
        legacy_tests.AuthenticationTests.setUp(self)
        search.cache.clear(); search.attempts.clear()
        self.setup_owner()

    def test_clock_formats_timezone_and_yandex_default_saved(self):
        config = self.client.get('/api/admin/settings').json()
        self.assertEqual(config['clock_format'], '24h')
        self.assertEqual(config['timezone'], 'Asia/Seoul')
        self.assertEqual(self.client.get('/api/portal').json()['additionalClocks'], [])
        for mode in ('12h', '24h'):
            result = self.client.put('/api/admin/settings', json=config | {'clock_format': mode, 'timezone': 'America/New_York', 'search_engine': 'y'}, headers=HEADERS)
            self.assertEqual(result.status_code, 200, result.text)
            fresh = self.client.get('/api/portal').json()
            self.assertEqual(fresh['clock']['format'], mode)
            self.assertEqual(fresh['clock']['timezone'], 'America/New_York')
            self.assertEqual(fresh['search']['default'], 'y')
            self.assertEqual(fresh['search']['engines']['y'], ['https://yandex.com/search/?text=', 'Yandex'])
        for change in ({'clock_format': 'bad'}, {'timezone': 'invalid/time'}, {'search_engine': 'bad'}):
            self.assertEqual(self.client.put('/api/admin/settings', json=config | change, headers=HEADERS).status_code, 422)

    def test_legacy_clock_upgrade_preserves_timezone_and_other_settings(self):
        with SessionLocal.begin() as db:
            db.delete(db.get(Migration, 'single-clock-search-providers-v1'))
            row = db.get(Setting, 'portal')
            config = dict(row.value)
            config['clock'] = {'format': 'k:i p', 'timezone': 'Asia/Tokyo'}
            config['additionalClocks'] = [{'label': 'UA', 'timezone': 'Europe/Kyiv'}]
            config['search'] = {'default': 'g', 'engines': {'g': ['https://google.com/search?q=', 'Google']}}
            row.value = config
        migrate()
        first = self.client.get('/api/portal').json()
        self.assertEqual(first['clock'], {'format': '24h', 'timezone': 'Asia/Tokyo'})
        self.assertEqual(first['additionalClocks'], [])
        self.assertEqual(first['search']['default'], 'g')
        config = self.client.get('/api/admin/settings').json()
        self.client.put('/api/admin/settings', json=config | {'clock_format': '12h'}, headers=HEADERS)
        migrate()
        self.assertEqual(self.client.get('/api/portal').json()['clock']['format'], '12h')

    def test_tab_animation_setting_persists_and_is_included_in_backup(self):
        from app.services.backups import export_document, open_document
        from app.db.models import User
        config = self.client.get('/api/admin/settings').json()
        self.assertTrue(config['tab_animation'])
        for enabled in (False, True):
            response = self.client.put('/api/admin/settings', json=config | {'tab_animation':enabled}, headers=HEADERS)
            self.assertEqual(response.status_code, 200, response.text)
            self.assertEqual(self.client.get('/api/admin/settings').json()['tab_animation'], enabled)
            self.assertEqual(self.client.get('/api/portal').json()['tabAnimation'], enabled)
            with SessionLocal() as db:
                document = export_document(db, db.scalar(select(User)), include_settings=True)
                self.assertEqual(document['settings']['tab_animation'], enabled)
                self.assertEqual(open_document(document, None)['settings']['tab_animation'], enabled)

    def test_shelf_display_persists_and_round_trips_with_legacy_backups(self):
        from app.services.backups import export_document, open_document
        from app.db.models import User
        config = self.client.get('/api/admin/settings').json()
        self.assertEqual(config['bookmark_shelf_display'], 'labels')
        response = self.client.put('/api/admin/settings', json=config | {'bookmark_shelf_display': 'icons'}, headers=HEADERS)
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(self.client.get('/api/admin/settings').json()['bookmark_shelf_display'], 'icons')
        self.assertEqual(self.client.get('/api/portal').json()['bookmarkShelfDisplay'], 'icons')
        with SessionLocal() as db:
            document = export_document(db, db.scalar(select(User)), include_settings=True)
        self.assertEqual(open_document(document, None)['settings']['bookmark_shelf_display'], 'icons')
        preview = self.client.post('/api/backups/import-preview', json={'document': document}, headers=HEADERS)
        self.assertEqual(preview.status_code, 200, preview.text)
        self.client.put('/api/admin/settings', json=config, headers=HEADERS)
        restored = self.client.post('/api/backups/import', json={'preview_id': preview.json()['preview_id'], 'apply_settings': True}, headers=HEADERS)
        self.assertEqual(restored.status_code, 200, restored.text)
        self.assertEqual(self.client.get('/api/portal').json()['bookmarkShelfDisplay'], 'icons')
        del document['settings']['bookmark_shelf_display']
        self.assertEqual(open_document(document, None)['settings']['bookmark_shelf_display'], 'labels')
        self.assertEqual(self.client.put('/api/admin/settings', json=config | {'bookmark_shelf_display': 'invalid'}, headers=HEADERS).status_code, 422)

    def test_search_open_mode_is_saved_in_portal_and_restored_from_backup(self):
        config = self.client.get('/api/admin/settings').json()
        self.assertEqual(config['search_open_mode'], 'same_tab')
        for mode in ('new_tab', 'same_tab', 'new_tab'):
            saved = self.client.put('/api/admin/settings', json=config | {'search_open_mode': mode}, headers=HEADERS)
            self.assertEqual(saved.status_code, 200, saved.text)
            self.assertEqual(self.client.get('/api/admin/settings').json()['search_open_mode'], mode)
            self.assertEqual(self.client.get('/api/portal').json()['search']['openMode'], mode)
        exported = self.client.post('/api/backups/export', json={'include_settings': True, 'include_images': False}, headers=HEADERS)
        self.assertEqual(exported.status_code, 200, exported.text)
        document = exported.json()
        self.assertEqual(document['settings']['search_open_mode'], 'new_tab')
        preview = self.client.post('/api/backups/import-preview', json={'document': document}, headers=HEADERS).json()
        self.client.put('/api/admin/settings', json=config, headers=HEADERS)
        restored = self.client.post('/api/backups/import', json={'preview_id': preview['preview_id'], 'apply_settings': True}, headers=HEADERS)
        self.assertEqual(restored.status_code, 200, restored.text)
        self.assertEqual(self.client.get('/api/portal').json()['search']['openMode'], 'new_tab')
        del document['settings']['search_open_mode']
        from app.services.backups import open_document
        self.assertEqual(open_document(document, None)['settings']['search_open_mode'], 'same_tab')
        self.assertEqual(self.client.put('/api/admin/settings', json=config | {'search_open_mode': 'invalid'}, headers=HEADERS).status_code, 422)

    def test_provider_cache_isolation_and_complete_korean_query(self):
        def reply(query, provider): return [query+' '+provider]
        with patch('app.api.search.provider_suggestions', new_callable=AsyncMock, side_effect=reply) as upstream:
            for provider in ('d', 'y', 'd', 'y'):
                result = self.client.post('/api/search/suggestions', json={'query': '한글 마지막 글자', 'provider': provider}, headers=HEADERS)
                self.assertEqual(result.status_code, 200, result.text)
                self.assertEqual(result.json()['suggestions'], ['한글 마지막 글자 '+provider])
            self.assertEqual(upstream.await_count, 2)
            upstream.assert_any_await('한글 마지막 글자', 'd')
            upstream.assert_any_await('한글 마지막 글자', 'y')
        self.assertEqual(self.client.post('/api/search/suggestions', json={'query': 'docker', 'provider': 'https://evil.test'}, headers=HEADERS).status_code, 422)
        with patch('app.api.search.provider_suggestions', new_callable=AsyncMock) as upstream:
            self.assertEqual(self.client.post('/api/search/suggestions', json={'query': '192.168.1.9', 'provider': 'd'}, headers=HEADERS).json()['suggestions'], [])
            upstream.assert_not_awaited()


class SuggestionProviders(unittest.IsolatedAsyncioTestCase):
    async def fetch(self, provider, handler):
        original = httpx.AsyncClient
        with patch('app.api.search.httpx.AsyncClient', side_effect=lambda **kw: original(transport=httpx.MockTransport(handler), **kw)):
            return await search.provider_suggestions('한글 검색', provider)

    async def test_fixed_endpoints_params_and_json(self):
        for provider, host, path, query_key in [('d', 'duckduckgo.com', '/ac/', 'q'), ('y', 'suggest.yandex.com', '/suggest-ff.cgi', 'part')]:
            def handler(request):
                self.assertEqual((request.url.host, request.url.path), (host, path))
                self.assertEqual(request.url.params[query_key], '한글 검색')
                self.assertNotIn('cookie', request.headers)
                self.assertNotIn('authorization', request.headers)
                return httpx.Response(200, json=['한글 검색', ['한글 검색 결과', '한글 검색 결과', 'https://private.test', 123]])
            self.assertEqual(await self.fetch(provider, handler), ['한글 검색 결과'])

    async def test_unavailable_empty_redirect_malformed_and_oversized(self):
        for provider in ('d', 'y'):
            self.assertEqual(await self.fetch(provider, lambda r: httpx.Response(200, json=['query', []])), [])
            for status, body in [(302, b''), (429, b''), (200, b'not-json'), (200, b'x'*65537), (200, b'{"error": true}')]:
                self.assertIsNone(await self.fetch(provider, lambda r: httpx.Response(status, content=body)))
