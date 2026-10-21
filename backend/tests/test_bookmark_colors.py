import unittest
from sqlalchemy import select

import test_auth as legacy_tests
from test_auth import HEADERS
from app.db.migrations import migrate
from app.db.models import Bookmark, Migration, SharedLink
from app.db.session import SessionLocal
from app.services.portal import default_config


class BookmarkColorTests(unittest.TestCase):
    setUp = legacy_tests.AuthenticationTests.setUp
    tearDown = legacy_tests.AuthenticationTests.tearDown
    setup_owner = legacy_tests.AuthenticationTests.setup_owner

    def test_default_auto_custom_and_reset_survive_reorder(self):
        self.setup_owner()
        category = self.client.get('/api/portal').json()['tabs'][0]['categories'][0]
        self.assertTrue(all(link['icon_color'] == 'auto' for link in category['links']))
        payload = {'category_id': category['id'], 'name': 'My link', 'url': 'https://my.test', 'icon': 'world'}
        created = self.client.post('/api/bookmarks', json=payload, headers=HEADERS)
        self.assertEqual(created.status_code, 200, created.text)
        row = created.json()
        self.assertEqual(row['icon_color'], 'auto')
        path = '/api/bookmarks/'+row['id']
        response = self.client.put(path, json=payload | {'icon_color': '#123456'}, headers=HEADERS)
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(self.client.get(path).json()['icon_color'], '#123456')
        ids = [link['id'] for link in self.client.get('/api/portal').json()['tabs'][0]['categories'][0]['links']]
        result = self.client.post('/api/reorder', json={'kind': 'bookmarks', 'parent_id': category['id'], 'ids': ids[::-1]}, headers=HEADERS)
        self.assertEqual(result.status_code, 200, result.text)
        self.assertEqual(self.client.get(path).json()['icon_color'], '#123456')
        self.assertEqual(self.client.put(path, json=payload | {'icon_color': 'auto'}, headers=HEADERS).status_code, 200)
        self.assertEqual(self.client.get(path).json()['icon_color'], 'auto')
        self.assertEqual(self.client.put(path, json=payload | {'icon_color': 'var(--red)'}, headers=HEADERS).status_code, 422)

    def test_shared_links_keep_auto_or_explicit_color_on_single_and_bulk_add(self):
        self.setup_owner()
        category = self.client.get('/api/portal').json()['tabs'][0]['categories'][0]['id']
        with SessionLocal.begin() as db:
            auto = SharedLink(name='Shared auto', url='https://shared-auto.test/', source_name='Fixture', published=True)
            custom = SharedLink(name='Shared custom', url='https://shared-custom.test/', source_name='Fixture', icon_color='#ff1234', published=True)
            db.add_all([auto, custom]); db.flush()
            ids = [auto.id, custom.id]
        result = self.client.post('/api/library/'+ids[0]+'/add', json={'category_id': category}, headers=HEADERS)
        self.assertEqual(result.status_code, 200, result.text)
        self.assertEqual(self.client.get('/api/bookmarks/'+result.json()['id']).json()['icon_color'], 'auto')
        self.assertEqual(self.client.post('/api/library/add', json={'category_id': category, 'link_ids': [ids[1]]}, headers=HEADERS).status_code, 200)
        with SessionLocal() as db:
            self.assertEqual(db.scalar(select(Bookmark).where(Bookmark.url=='https://shared-custom.test/')).icon_color, '#ff1234')
        settings = {'name': 'Shared custom', 'icon': 'world', 'published': True, 'icon_color': 'auto'}
        self.assertEqual(self.client.put('/api/admin/library/'+ids[1], json=settings, headers=HEADERS).status_code, 200)
        self.assertEqual(next(link for link in self.client.get('/api/library').json() if link['id']==ids[1])['icon_color'], 'auto')

    def test_upgrade_only_inherited_seed_colors_and_is_idempotent(self):
        self.setup_owner()
        defaults = default_config()['tabs'][0]['categories'][0]['links']
        with SessionLocal.begin() as db:
            db.delete(db.get(Migration, 'automatic-icon-colors-v1'))
            inherited = db.scalar(select(Bookmark).where(Bookmark.name==defaults[0]['name']))
            inherited.icon_color = defaults[0]['icon_color']
            manual = db.scalar(select(Bookmark).where(Bookmark.name==defaults[1]['name']))
            manual.icon_color = '#123456'
            inherited_id, manual_id = inherited.id, manual.id
            db.add(Bookmark(user_id=1, category_id=inherited.category_id, name='Personal', url='https://personal.test', icon_color='#89b4fa'))
        migrate()
        with SessionLocal() as db:
            self.assertEqual(db.get(Bookmark, inherited_id).icon_color, 'auto')
            self.assertEqual(db.get(Bookmark, manual_id).icon_color, '#123456')
            self.assertEqual(db.scalar(select(Bookmark).where(Bookmark.name=='Personal')).icon_color, '#89b4fa')
        with SessionLocal.begin() as db:
            db.get(Bookmark, inherited_id).icon_color = defaults[0]['icon_color']
        migrate()
        with SessionLocal() as db:
            self.assertEqual(db.get(Bookmark, inherited_id).icon_color, defaults[0]['icon_color'])
