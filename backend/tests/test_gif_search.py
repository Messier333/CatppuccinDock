import io
import unittest
from unittest.mock import MagicMock, patch

from fastapi import HTTPException
from fastapi.testclient import TestClient
from sqlalchemy import inspect, text

import test_auth as auth_tests
from test_auth import HEADERS
from test_backgrounds import gif
from app.db.migrations import migrate
from app.db.models import BackgroundImage
from app.db.session import SessionLocal, engine
from app.main import app
from app.services.media import gif_search, remote_media


def commons_page():
    return {'pageid': 42, 'title': 'File:Rain.gif', 'index': 1, 'imageinfo': [{
        'mime': 'image/gif', 'url': 'https://upload.wikimedia.org/example.gif',
        'thumburl': 'https://upload.wikimedia.org/thumb.png', 'size': len(gif()), 'width': 64, 'height': 48,
        'extmetadata': {'Artist': {'value': '<a href="https://example.org/">Rain Author</a>'},
                        'LicenseShortName': {'value': 'CC BY-SA 4.0'},
                        'LicenseUrl': {'value': 'https://creativecommons.org/licenses/by-sa/4.0/'}}}]}


class GifSearchTests(unittest.TestCase):
    tearDown = auth_tests.AuthenticationTests.tearDown
    setup_owner = auth_tests.AuthenticationTests.setup_owner

    def setUp(self):
        auth_tests.AuthenticationTests.setUp(self)
        gif_search.cache.clear(); gif_search.budgets.clear()

    def import_image(self):
        with patch('app.services.media.gif_search.provider_json', return_value={'query': {'pages': [commons_page()]}}), \
                patch('app.services.media.gif_search.fetch_public', return_value=gif()) as fetch:
            response = self.client.post('/api/backgrounds/import', json={'provider': 'commons', 'item_id': '42'}, headers=HEADERS)
        self.assertEqual(response.status_code, 200, response.text)
        self.assertLessEqual(fetch.call_count,1)
        if fetch.call_count:
            self.assertEqual(fetch.call_args.args[0],'https://upload.wikimedia.org/example.gif')
            self.assertEqual(fetch.call_args.kwargs['max_bytes'],100*1024*1024)
        return response.json()

    def test_search_authentication_csrf_and_identifiers(self):
        self.assertEqual(self.client.get('/api/backgrounds/search?provider=commons&q=rain').status_code, 401)
        self.assertEqual(self.client.post('/api/backgrounds/import', json={'provider': 'commons', 'item_id': '42'}, headers=HEADERS).status_code, 401)
        self.setup_owner()
        self.assertEqual(self.client.post('/api/backgrounds/import', json={'provider': 'commons', 'item_id': '42'}).status_code, 403)
        with patch('app.services.media.gif_search.provider_json') as request:
            for provider, item_id in (('commons', 'https://127.0.0.1/'), ('openverse', '../private')):
                self.assertEqual(self.client.post('/api/backgrounds/import', json={'provider': provider, 'item_id': item_id}, headers=HEADERS).status_code, 422)
            request.assert_not_called()
        self.assertEqual(self.client.get('/api/backgrounds/search?provider=arbitrary&q=rain').status_code, 422)
        self.assertEqual(self.client.get('/api/backgrounds/search?page=21&q=rain').status_code, 422)
        self.assertEqual(self.client.get('/api/backgrounds/search?provider=commons&q=').json()['items'], [])

    def test_search_is_paginated_cached_and_does_not_download(self):
        self.setup_owner()
        result = {'query': {'pages': [commons_page()]}, 'continue': {'gsroffset': 12}}
        with patch('app.services.media.gif_search.provider_json', return_value=result) as request, patch('app.services.media.gif_search.fetch_public') as download:
            first = self.client.get('/api/backgrounds/search?provider=commons&q=rain').json()
            second = self.client.get('/api/backgrounds/search?provider=commons&q=rain').json()
            self.assertEqual(first, second)
            self.assertEqual(request.call_count, 1)
            download.assert_not_called()
            params = request.call_args.args[1]
            self.assertEqual(params['gsrnamespace'], 6)
            self.assertIn('filemime:image/gif', params['gsrsearch'])
            item = first['items'][0]
            self.assertNotIn('url', item)
            self.assertEqual(item['source']['author'], 'Rain Author')
            self.assertTrue(first['has_more'])
            self.assertEqual(item['source']['license'], 'CC BY-SA 4.0')
            self.assertEqual(self.client.get('/api/backgrounds/search?provider=commons&q=rain&page=2').status_code, 200)
            self.assertEqual(request.call_args.args[1]['gsroffset'], 12)
        self.assertEqual(self.client.get('/api/backgrounds').json()['items'], [])

    def test_openverse_gif_filter_and_source_metadata(self):
        self.setup_owner()
        item = {'id': '12345678-1234-1234-1234-123456789abc', 'title': 'Rain', 'url': 'https://example.org/rain.gif',
                'thumbnail': 'https://example.org/thumb.png', 'foreign_landing_url': 'https://example.org/rain',
                'filetype': 'gif', 'creator': 'Author', 'license': 'cc0', 'license_version': '1.0',
                'license_url': 'https://creativecommons.org/publicdomain/zero/1.0/'}
        with patch('app.services.media.gif_search.provider_json', return_value={'results': [item], 'page_count': 2}) as request:
            result = self.client.get('/api/backgrounds/search?provider=openverse&q=rain').json()
            self.assertEqual(request.call_args.args[1]['extension'], 'gif')
            self.assertEqual(result['items'][0]['source']['provider'], 'openverse')
            self.assertTrue(result['has_more'])

    def test_large_search_result_import_is_optimized_and_keeps_source(self):
        self.setup_owner()
        raw = gif()+b'\x00'*(10*1024*1024)
        page = commons_page(); page['imageinfo'][0]['size'] = len(raw)
        with patch('app.services.media.gif_search.provider_json', return_value={'query': {'pages': [page]}}), \
                patch('app.services.media.gif_search.fetch_public', return_value=raw):
            result = self.client.get('/api/backgrounds/search?provider=commons&q=large')
            self.assertEqual(len(result.json()['items']),1)
            response = self.client.post('/api/backgrounds/import',json={'provider':'commons','item_id':'42'},headers=HEADERS)
        self.assertEqual(response.status_code,200,response.text)
        image=response.json()
        self.assertLess(image['byte_size'],10*1024*1024)
        self.assertGreater(image['frames'],1)
        self.assertEqual(image['source']['author'],'Rain Author')
        stored=self.client.get('/api/backgrounds/'+image['id']+'/content').content
        self.assertEqual(len(stored),image['byte_size'])
        doc=self.client.post('/api/backups/export',json={},headers=HEADERS).json()
        self.assertEqual(doc['images'][0]['source'],image['source'])
        self.assertEqual(self.client.post('/api/backups/import-preview',json={'document':doc},headers=HEADERS).status_code,200)
        self.assertEqual(self.client.get('/api/backgrounds').json()['limits']['max_input_bytes'],100*1024*1024)

    def test_missing_alpha_topic_is_a_successful_empty_search(self):
        self.setup_owner()
        with patch('app.services.media.wallpaper_gifs.page_html',side_effect=remote_media.RemoteMediaError('missing',404)):
            response=self.client.get('/api/backgrounds/search?provider=alphacoders&q=DEV')
        self.assertEqual(response.status_code,200,response.text)
        self.assertEqual(response.json()['items'],[])

    def test_import_keeps_original_bytes_locally_when_provider_is_down(self):
        self.setup_owner()
        image = self.import_image()
        with patch('app.services.media.gif_search.provider_json', side_effect=TimeoutError):
            response = self.client.get('/api/backgrounds/search?provider=commons&q=offline')
            self.assertEqual(response.status_code, 504)
            self.assertEqual(self.client.get('/api/backgrounds/'+image['id']+'/content').content, gif())
        self.assertEqual(image['source']['author'], 'Rain Author')
        with SessionLocal() as db:
            row = db.get(BackgroundImage, image['id'])
            self.assertEqual(row.data, gif())
            self.assertEqual(row.source, image['source'])
        self.client.post('/api/admin/users', json={'username': 'member', 'password': 'a-member-password'}, headers=HEADERS)
        with TestClient(app) as member:
            member.post('/api/auth/login', json={'username': 'member', 'password': 'a-member-password'}, headers=HEADERS)
            self.assertEqual(member.get('/api/backgrounds').json()['items'], [])
            self.assertEqual(member.get('/api/backgrounds/'+image['id']+'/content').status_code, 404)

    def test_import_deduplicates_and_preserves_attribution_from_upload(self):
        self.setup_owner()
        upload = self.client.post('/api/backgrounds', content=gif(), headers={**HEADERS, 'Content-Type': 'image/gif'}).json()
        first = self.import_image(); second = self.import_image()
        self.assertEqual(first['id'], upload['id'])
        self.assertEqual(second['id'], first['id'])
        self.assertEqual(self.client.get('/api/backgrounds').json()['items'], [second])
        self.assertEqual(second['source']['license'], 'CC BY-SA 4.0')

    def test_invalid_media_and_upstream_errors_do_not_store_files(self):
        self.setup_owner()
        for error, status in ((TimeoutError(), 504), (remote_media.RemoteMediaError('busy', 429), 429), (ValueError('private IP'), 502)):
            with patch('app.services.media.gif_search.download', side_effect=error):
                response = self.client.post('/api/backgrounds/import', json={'provider': 'commons', 'item_id': '42'}, headers=HEADERS)
                self.assertEqual(response.status_code, status)
        with patch('app.services.media.gif_search.download', return_value=(b'<svg/>', 'fake', None)):
            self.assertEqual(self.client.post('/api/backgrounds/import', json={'provider': 'commons', 'item_id': '42'}, headers=HEADERS).status_code, 422)
        self.assertEqual(self.client.get('/api/backgrounds').json()['items'], [])

    def test_search_and_import_have_bounded_request_budgets(self):
        self.setup_owner()
        with patch('app.services.media.gif_search.search', return_value={'items': []}), patch('app.services.media.gif_search.budget_clock', return_value=600):
            for _ in range(20):
                self.assertEqual(self.client.get('/api/backgrounds/search?provider=commons&q=rain').status_code, 200)
            self.assertEqual(self.client.get('/api/backgrounds/search?provider=commons&q=rain').status_code, 429)
        with patch('app.services.media.gif_search.download', side_effect=HTTPException(404, 'missing')) as request:
            config=self.client.get('/api/admin/backgrounds').json();config.pop('has_pixabay_key');config['server_per_day']=6
            self.assertEqual(self.client.put('/api/admin/backgrounds',json=config,headers=HEADERS).status_code,200)
            for _ in range(6):
                self.assertEqual(self.client.post('/api/backgrounds/import', json={'provider': 'commons', 'item_id': '42'}, headers=HEADERS).status_code, 404)
            self.assertEqual(self.client.post('/api/backgrounds/import', json={'provider': 'commons', 'item_id': '42'}, headers=HEADERS).status_code, 429)
            self.assertEqual(request.call_count, 6)

    def test_new_tabs_default_to_no_background_and_sources_survive_backup(self):
        self.setup_owner()
        image = self.import_image()
        tab = self.client.post('/api/tabs', json={'name': 'No background'}, headers=HEADERS)
        self.assertEqual(tab.status_code, 200)
        current = next(row for row in self.client.get('/api/portal').json()['tabs'] if row['id'] == tab.json()['id'])
        self.assertEqual(current['banner'], 'none'); self.assertIsNone(current['background_id'])
        doc = self.client.post('/api/backups/export', json={}, headers=HEADERS).json()
        self.assertEqual(doc['images'][0]['source'], image['source'])
        self.assertEqual(doc['tabs'][-1]['banner'], 'none')
        self.client.delete('/api/backgrounds/'+image['id'], headers=HEADERS)
        preview = self.client.post('/api/backups/import-preview', json={'document': doc}, headers=HEADERS)
        self.assertEqual(preview.status_code, 200, preview.text)
        imported = self.client.post('/api/backups/import', json={'preview_id': preview.json()['preview_id'], 'mode': 'replace'}, headers=HEADERS)
        self.assertEqual(imported.status_code, 200, imported.text)
        restored = self.client.get('/api/backgrounds').json()['items'][0]
        self.assertEqual(restored['source'], image['source'])
        self.assertEqual(self.client.get('/api/backgrounds/'+restored['id']+'/content').content, gif())

    def test_source_migration_preserves_existing_gif_bytes(self):
        self.setup_owner()
        image = self.import_image()
        with engine.begin() as connection:
            connection.execute(text('ALTER TABLE dock_background_images DROP COLUMN source'))
        migrate(); migrate()
        with SessionLocal() as db:
            current = db.get(BackgroundImage, image['id'])
            self.assertIsNone(current.source)
            self.assertEqual(current.data, gif())
        self.assertIn('source', {column['name'] for column in inspect(engine).get_columns('dock_background_images')})


class PublicMediaTests(unittest.TestCase):
    def test_invalid_schemes_credentials_ports_and_private_addresses_are_rejected(self):
        for url in ('http://example.org/x.gif', 'file:///tmp/file.gif', 'https://a:b@example.org/x.gif', 'https://example.org:8080/x.gif'):
            with self.assertRaises(ValueError):
                remote_media.https_url(url)
        with patch('app.services.media.remote_media.socket.create_connection') as connect:
            with self.assertRaises(ValueError):
                remote_media.fetch_public('https://127.0.0.1/x.gif', max_bytes=100, accept='image/gif')
            connect.assert_not_called()

    def test_download_pins_dns_bounds_bytes_and_revalidates_redirects(self):
        def response(status=200, headers=None, data=b'GIF89a;'):
            result = MagicMock(status=status)
            headers = headers or {'Content-Type': 'image/gif'}
            result.getheader.side_effect = lambda key, default=None: headers.get(key, default)
            result.read.side_effect = io.BytesIO(data).read
            result.isclosed.return_value = False
            return result
        sock = MagicMock()
        context = MagicMock(); context.wrap_socket.return_value = sock
        with patch('app.services.media.remote_media.safe_addresses', return_value=['93.184.216.34']) as dns, \
                patch('app.services.media.remote_media.socket.create_connection', return_value=sock) as connect, \
                patch('app.services.media.remote_media.ssl.create_default_context', return_value=context), \
                patch('app.services.media.remote_media.http.client.HTTPConnection') as connection:
            connection.return_value.getresponse.return_value = response()
            self.assertEqual(remote_media.fetch_public('https://example.org/x.gif', max_bytes=100, accept='image/gif'), b'GIF89a;')
            self.assertEqual(connect.call_args.args[0], ('93.184.216.34', 443))
            dns.assert_called_with('example.org', 443, False)
            context.wrap_socket.assert_called_with(sock, server_hostname='example.org')
            # HTTPResponse may close the socket as soon as its last bytes are read.
            closed = response(); closed.isclosed.return_value = True
            connection.return_value.getresponse.return_value = closed
            sock.settimeout.reset_mock()
            self.assertEqual(remote_media.fetch_public('https://example.org/x.gif', max_bytes=100, accept='image/gif'), b'GIF89a;')
            self.assertEqual(sock.settimeout.call_count, 2)
            headers = [call.args[0] for call in connection.return_value.putheader.call_args_list]
            self.assertNotIn('Cookie', headers); self.assertNotIn('Authorization', headers)
            for supplied in (response(headers={'Content-Type': 'image/gif', 'Content-Length': '101'}), response(data=b'x'*101)):
                connection.return_value.getresponse.return_value = supplied
                with self.assertRaises(remote_media.RemoteMediaError) as error:
                    remote_media.fetch_public('https://example.org/x.gif', max_bytes=100, accept='image/gif')
                self.assertEqual(error.exception.status, 413)
            connection.return_value.getresponse.return_value = response(status=302, headers={'Location': 'https://127.0.0.1/x.gif'})
            dns.side_effect = [['93.184.216.34'], ValueError('private address')]
            with self.assertRaises(ValueError):
                remote_media.fetch_public('https://example.org/x.gif', max_bytes=100, accept='image/gif')
