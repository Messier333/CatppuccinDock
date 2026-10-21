from io import BytesIO
import unittest
from unittest.mock import patch

from fastapi.testclient import TestClient
from PIL import Image
from sqlalchemy import func, inspect, select, text

import test_auth as legacy_tests
from test_auth import HEADERS
from app.db.migrations import migrate
from app.db.models import BackgroundImage, Bookmark, Tab
from app.db.session import SessionLocal, engine
from app.main import app


def gif(color='red'):
    stream = BytesIO()
    first = Image.new('RGB', (64, 48), color)
    second = Image.new('RGB', (64, 48), 'blue')
    first.save(stream, format='GIF', save_all=True, append_images=[second], duration=100, loop=0)
    return stream.getvalue()


class BackgroundTests(unittest.TestCase):
    setUp = legacy_tests.AuthenticationTests.setUp
    tearDown = legacy_tests.AuthenticationTests.tearDown
    setup_owner = legacy_tests.AuthenticationTests.setup_owner

    def upload(self, data=None, **headers):
        return self.client.post('/api/backgrounds', content=gif() if data is None else data,
                                headers={**HEADERS, 'Content-Type': 'image/gif', 'X-File-Name': '%EB%82%B4-%EB%B0%B0%EA%B2%BD.gif', **headers})

    def image(self):
        response = self.upload()
        self.assertEqual(response.status_code, 200, response.text)
        return response.json()

    def test_animated_gif_survives_database_roundtrip_and_conditional_fetch(self):
        self.setup_owner()
        image = self.image()
        self.assertEqual((image['name'], image['width'], image['height'], image['frames']), ('내-배경.gif', 64, 48, 2))
        path = '/api/backgrounds/'+image['id']+'/content'
        response = self.client.get(path)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.content, gif())
        self.assertEqual(response.headers['content-type'], 'image/gif')
        self.assertEqual(response.headers['x-content-type-options'], 'nosniff')
        self.assertEqual(response.headers['cache-control'], 'private, no-cache')
        self.assertEqual(response.headers['vary'], 'Cookie')
        self.assertIn('sandbox', response.headers['content-security-policy'])
        cached = self.client.get(path, headers={'If-None-Match': 'W/'+response.headers['etag']})
        self.assertEqual(cached.status_code, 304)
        self.assertFalse(cached.content)
        self.assertEqual(self.client.get(path, headers={'If-None-Match': '"different"'}).content, gif())
        listing = self.client.get('/api/backgrounds').json()
        self.assertEqual(listing['items'], [image])
        self.assertNotIn('data', str(listing))
        with SessionLocal() as db:
            row = db.get(BackgroundImage, image['id'])
            self.assertIn('data', inspect(row).unloaded)
            self.assertEqual(row.data, gif())

    def test_tab_selection_usage_and_revert_before_delete(self):
        self.setup_owner()
        image = self.image()
        tab = self.client.get('/api/portal').json()['tabs'][0]
        path = '/api/tabs/'+tab['id']
        payload = {key: tab[key] for key in ('name', 'banner', 'position')}
        self.assertEqual(self.client.put(path, json={**payload, 'background_id': image['id']}, headers=HEADERS).status_code, 200)
        self.assertEqual(self.client.get('/api/portal').json()['tabs'][0]['background_id'], image['id'])
        self.assertEqual(self.client.get('/api/backgrounds').json()['items'][0]['used_by'], 1)
        self.assertEqual(self.client.delete('/api/backgrounds/'+image['id'], headers=HEADERS).status_code, 409)
        self.assertEqual(self.client.put(path, json={**payload, 'background_id': None}, headers=HEADERS).status_code, 200)
        self.assertIsNone(self.client.get('/api/portal').json()['tabs'][0]['background_id'])
        self.assertEqual(self.client.delete('/api/backgrounds/'+image['id'], headers=HEADERS).status_code, 200)
        self.assertEqual(self.client.get('/api/backgrounds/'+image['id']+'/content').status_code, 404)
        self.assertEqual(self.client.put(path, json={**payload, 'background_id': image['id']}, headers=HEADERS).status_code, 404)

    def test_upload_can_be_reused_across_tabs_and_kept_after_tab_deletion(self):
        self.setup_owner()
        image = self.image()
        ids = []
        for name in ('One', 'Two'):
            response = self.client.post('/api/tabs', json={'name': name, 'background_id': image['id']}, headers=HEADERS)
            self.assertEqual(response.status_code, 200, response.text)
            ids.append(response.json()['id'])
        self.assertEqual(self.client.get('/api/backgrounds').json()['items'][0]['used_by'], 2)
        self.client.delete('/api/tabs/'+ids[0], headers=HEADERS)
        self.assertEqual(self.client.get('/api/backgrounds').json()['items'][0]['used_by'], 1)
        self.client.delete('/api/tabs/'+ids[1], headers=HEADERS)
        self.assertEqual(self.client.get('/api/backgrounds').json()['items'][0]['used_by'], 0)
        self.assertEqual(self.client.get('/api/backgrounds/'+image['id']+'/content').content, gif())

    def test_members_have_own_library_and_cannot_fetch_assign_or_delete_others(self):
        self.setup_owner()
        image = self.image()
        self.client.post('/api/admin/users', json={'username': 'member', 'password': 'a-member-password'}, headers=HEADERS)
        member = TestClient(app)
        self.assertEqual(member.post('/api/auth/login', json={'username': 'member', 'password': 'a-member-password'}, headers=HEADERS).status_code, 200)
        self.assertEqual(member.get('/api/backgrounds').json()['items'], [])
        self.assertEqual(member.get('/api/backgrounds/'+image['id']+'/content', headers={'If-None-Match': '*'}).status_code, 404)
        self.assertEqual(member.delete('/api/backgrounds/'+image['id'], headers=HEADERS).status_code, 404)
        self.assertEqual(member.post('/api/tabs', json={'name': 'Stolen', 'background_id': image['id']}, headers=HEADERS).status_code, 404)
        tab = member.get('/api/portal').json()['tabs'][0]
        self.assertEqual(member.put('/api/tabs/'+tab['id'], json={'name': tab['name'], 'background_id': image['id']}, headers=HEADERS).status_code, 404)
        own = member.post('/api/backgrounds', content=gif(), headers={**HEADERS, 'Content-Type': 'image/gif'})
        self.assertEqual(own.status_code, 200, own.text)
        self.assertNotEqual(own.json()['id'], image['id'])
        self.assertEqual(self.client.get('/api/backgrounds/'+own.json()['id']+'/content').status_code, 404)

    def test_authentication_and_mutation_header_are_required(self):
        self.assertEqual(self.upload().status_code, 401)
        self.assertEqual(self.client.get('/api/backgrounds').status_code, 401)
        self.setup_owner()
        image = self.image()
        self.assertEqual(self.client.post('/api/backgrounds', content=gif(), headers={'Content-Type': 'image/gif'}).status_code, 403)
        self.assertEqual(self.client.delete('/api/backgrounds/'+image['id']).status_code, 403)
        self.client.cookies.clear()
        self.assertEqual(self.client.get('/api/backgrounds/'+image['id']+'/content', headers={'If-None-Match': '*'}).status_code, 401)

    def test_invalid_mime_disguised_images_and_truncated_gif_are_rejected(self):
        self.setup_owner()
        png = BytesIO(); Image.new('RGB', (1, 1)).save(png, format='PNG')
        self.assertEqual(self.upload(**{'Content-Type': 'text/html'}).status_code, 415)
        for data in (b'<svg onload="alert(1)"/>', png.getvalue(), gif()[:35]+b';', b'GIF89a;', gif()[:-1]):
            self.assertEqual(self.upload(data).status_code, 422)
        self.assertEqual(self.client.get('/api/backgrounds').json()['items'], [])

    def test_valid_gif_trailing_padding_is_preserved(self):
        self.setup_owner()
        for padding in (b'\x00'*9, b'\r\n'):
            raw = gif()+padding
            response = self.upload(raw)
            self.assertEqual(response.status_code, 200, response.text)
            self.assertEqual(self.client.get('/api/backgrounds/'+response.json()['id']+'/content').content, raw)
        self.assertEqual(self.upload(gif()+b'<script>alert(1)</script>').status_code, 422)

    def test_body_size_is_bounded_even_for_chunked_requests(self):
        self.setup_owner()
        self.assertEqual(self.upload(**{'Content-Length': str(100*1024*1024+1)}).status_code, 413)
        with patch('app.api.backgrounds.MAX_INPUT_BYTES', 64):
            response = self.client.post('/api/backgrounds', content=iter([b'GIF89a'+b'a'*24, b'b'*35]), headers={**HEADERS, 'Content-Type': 'image/gif'})
        self.assertEqual(response.status_code, 413)

    def test_storage_limits_are_satisfied_by_automatically_resized_upload(self):
        self.setup_owner()
        large = BytesIO(); Image.new('P', (4097, 1)).save(large, format='GIF')
        response = self.upload(large.getvalue())
        self.assertEqual(response.status_code, 200, response.text)
        self.assertLessEqual(response.json()['width'], 960)
        for constant in ('MAX_FRAMES', 'MAX_FRAME_PIXELS'):
            with patch('app.services.media.backgrounds.'+constant, 1):
                self.assertEqual(self.upload().status_code, 422)

    def test_duplicate_upload_reuses_file_and_does_not_consume_quota(self):
        self.setup_owner()
        with patch('app.api.backgrounds.MAX_FILES', 1):
            first = self.image()
            self.assertEqual(self.upload().json()['id'], first['id'])
            self.assertEqual(self.upload(gif('green')).status_code, 409)
        self.assertEqual(len(self.client.get('/api/backgrounds').json()['items']), 1)

    def test_background_and_selection_persist_across_repeated_startup_migration(self):
        self.setup_owner()
        image = self.image()
        response = self.client.post('/api/tabs', json={'name': 'Persist', 'background_id': image['id']}, headers=HEADERS)
        self.assertEqual(response.status_code, 200)
        migrate(); migrate()
        with SessionLocal() as db:
            self.assertEqual(db.get(Tab, response.json()['id']).background_id, image['id'])
            self.assertEqual(db.get(BackgroundImage, image['id']).data, gif())

    def test_old_tab_schema_upgrade_preserves_tabs_and_bookmarks(self):
        self.setup_owner()
        with SessionLocal() as db:
            tabs = [{key: getattr(row, key) for key in ('id', 'user_id', 'name', 'banner', 'position')} for row in db.scalars(select(Tab))]
            bookmark_count = db.scalar(select(func.count()).select_from(Bookmark))
        with engine.begin() as connection:
            connection.execute(text('DROP TABLE dock_tabs'))
            connection.execute(text('CREATE TABLE dock_tabs (id VARCHAR(36) PRIMARY KEY, user_id INTEGER NOT NULL, name VARCHAR(80) NOT NULL, banner VARCHAR(32) NOT NULL, position INTEGER NOT NULL)'))
            connection.execute(text('INSERT INTO dock_tabs (id,user_id,name,banner,position) VALUES (:id,:user_id,:name,:banner,:position)'), tabs)
        migrate(); migrate()
        with SessionLocal() as db:
            upgraded = list(db.scalars(select(Tab)))
            self.assertEqual(len(upgraded), len(tabs))
            self.assertTrue(all(row.background_id is None for row in upgraded))
            self.assertEqual(db.scalar(select(func.count()).select_from(Bookmark)), bookmark_count)
        self.assertEqual(self.client.get('/api/portal').status_code, 200)
