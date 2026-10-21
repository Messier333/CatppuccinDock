import unittest
from unittest.mock import MagicMock, patch
from fastapi.testclient import TestClient
from sqlalchemy import text
import test_auth as legacy
from test_auth import HEADERS
from app.main import app
from app.db.migrations import migrate
from app.db.models import Bookmark, BookmarkVisit, SharedLink, SharedPlacement
from app.db.session import SessionLocal, engine
from app.services import bookmark_metadata


class ProductivityTests(unittest.TestCase):
    setUp=legacy.AuthenticationTests.setUp
    tearDown=legacy.AuthenticationTests.tearDown
    setup_owner=legacy.AuthenticationTests.setup_owner

    def portal(self, client=None): return (client or self.client).get('/api/portal').json()
    def links(self, client=None): return [link for tab in self.portal(client)['tabs'] for category in tab['categories'] for link in category['links']]
    def member(self):
        self.client.post('/api/admin/users',json={'username':'productive-member','password':'a-member-password'},headers=HEADERS)
        member=TestClient(app);member.post('/api/auth/login',json={'username':'productive-member','password':'a-member-password'},headers=HEADERS)
        return member
    def bulk(self,ids,action,**extra): return self.client.post('/api/bookmark-tools/bulk',json={'ids':ids,'action':action,**extra},headers=HEADERS)

    def test_preferences_inherit_defaults_are_account_scoped_and_weather_uses_effective_location(self):
        self.setup_owner();member=self.member()
        default=self.client.get('/api/admin/settings').json()
        result=member.put('/api/account/preferences',json={'search_engine':'y','clock_format':'12h','timezone':'Asia/Tokyo','weather_location':'Tokyo','temperature_scale':'F','animation_mode':'on'},headers=HEADERS)
        self.assertEqual(result.status_code,200,result.text)
        portal=self.portal(member);self.assertEqual(portal['search']['default'],'y');self.assertEqual(portal['clock']['timezone'],'Asia/Tokyo');self.assertEqual(portal['clock']['format'],'12h');self.assertEqual(portal['animationMode'],'on')
        self.assertEqual(self.client.get('/api/admin/settings').json(),default)
        self.assertNotEqual(self.portal()['search']['default'],'y')
        with patch('app.api.weather.current_weather',return_value={'available':False}) as weather:
            member.get('/api/weather');weather.assert_awaited_once_with('Tokyo','F')
        with patch('app.api.weather.current_weather',return_value={'available':False}) as weather:
            member.post('/api/weather/refresh',headers=HEADERS);weather.assert_awaited_once_with('Tokyo','F',force=True)
        member.put('/api/account/preferences',json={},headers=HEADERS)
        self.assertEqual(self.portal(member)['temperature']['location'],default['weather_location'])
        self.assertEqual(member.get('/api/account/preferences').json()['overrides'],{})
        for data in ({'timezone':'bad/zone'},{'animation_mode':'bad'},{'user_id':1},{'weather_location':'  '}):
            self.assertEqual(member.put('/api/account/preferences',json=data,headers=HEADERS).status_code,422)
        self.assertEqual(member.put('/api/account/preferences',json={}).status_code,403)
        self.assertEqual(TestClient(app).get('/api/account/preferences').status_code,401)

    def test_favorites_recent_clicks_deletion_and_cross_account_isolation(self):
        self.setup_owner();member=self.member();link=self.links()[0];foreign=self.links(member)[0]
        self.assertEqual(member.put('/api/bookmark-tools/'+link['id']+'/favorite',json={'favorite':True},headers=HEADERS).status_code,404)
        self.assertEqual(member.post('/api/bookmark-tools/'+link['id']+'/visit',headers=HEADERS).status_code,404)
        self.client.put('/api/bookmark-tools/'+link['id']+'/favorite',json={'favorite':True},headers=HEADERS)
        for _ in range(2): self.client.post('/api/bookmark-tools/'+link['id']+'/visit',headers=HEADERS)
        self.assertTrue(self.client.get('/api/bookmarks/'+link['id']).json()['favorite'])
        self.assertEqual(self.portal()['recentBookmarks'],[link['id']]);self.assertEqual(self.portal(member)['recentBookmarks'],[])
        with SessionLocal() as db:self.assertEqual(db.get(BookmarkVisit,link['id']).count,2)
        member.post('/api/bookmark-tools/'+foreign['id']+'/visit',headers=HEADERS)
        self.client.delete('/api/bookmark-tools/recent',headers=HEADERS)
        self.assertEqual(self.portal()['recentBookmarks'],[]);self.assertEqual(self.portal(member)['recentBookmarks'],[foreign['id']])
        self.client.post('/api/bookmark-tools/'+link['id']+'/visit',headers=HEADERS)
        deleted=self.client.delete('/api/bookmarks/'+link['id'],headers=HEADERS).json()
        with SessionLocal() as db:self.assertIsNone(db.get(BookmarkVisit,link['id']))
        self.client.post('/api/trash/'+deleted['trash_id']+'/restore',headers=HEADERS)
        self.assertTrue(self.client.get('/api/bookmarks/'+link['id']).json()['favorite'])

    def test_hidden_shared_bookmarks_cannot_be_favorited_tracked_or_bulk_edited(self):
        self.setup_owner();member=self.member();link=self.links(member)[0]
        with SessionLocal.begin() as db:
            managed=SharedLink(name='Private',url='https://shared.test/',icon='world',source_name='Fixture',published=True,access_mode='restricted')
            db.add(managed);db.flush();sid=managed.id;db.add(SharedPlacement(bookmark_id=link['id'],link_id=sid))
        self.assertEqual(member.put('/api/bookmark-tools/'+link['id']+'/favorite',json={'favorite':True},headers=HEADERS).status_code,404)
        self.assertEqual(member.post('/api/bookmark-tools/'+link['id']+'/visit',headers=HEADERS).status_code,404)
        self.assertEqual(member.post('/api/bookmark-tools/bulk',json={'action':'delete','ids':[link['id']]},headers=HEADERS).status_code,409)
        with SessionLocal() as db:self.assertIsNotNone(db.get(Bookmark,link['id']))

    def test_bulk_move_and_icon_edits_are_atomic_owned_and_undoable(self):
        self.setup_owner();member=self.member();links=self.links()[:2];ids=[link['id'] for link in links];foreign=self.links(member)[0]
        destination=self.portal()['tabs'][1]['categories'][0]['id']
        for bad in ('missing',foreign['id']):
            self.assertEqual(self.bulk(ids+[bad],'move',category_id=destination).status_code,409)
            self.assertEqual(self.client.get('/api/bookmarks/'+ids[0]).json()['category_id'],links[0]['category_id'])
        self.assertEqual(self.bulk(ids,'move',category_id=foreign['category_id']).status_code,404)
        moved=self.bulk(ids,'move',category_id=destination)
        self.assertEqual(moved.status_code,200,moved.text)
        self.assertTrue(all(self.client.get('/api/bookmarks/'+bid).json()['category_id']==destination for bid in ids))
        undo=self.client.post('/api/trash/'+moved.json()['undo_id']+'/restore',headers=HEADERS);self.assertEqual(undo.status_code,200,undo.text)
        changed=self.bulk(ids,'icon',icon='simple-icons:github',icon_color='#aabbcc');self.assertEqual(changed.status_code,200,changed.text)
        self.assertEqual(self.client.get('/api/bookmarks/'+ids[1]).json()['icon'],'simple-icons:github')
        self.assertEqual(self.client.post('/api/trash/'+changed.json()['undo_id']+'/restore',headers=HEADERS).status_code,200)
        self.assertEqual(self.client.get('/api/bookmarks/'+ids[1]).json()['icon'],links[1]['icon'])
        self.assertEqual(self.bulk(ids,'icon',icon='simple-icons:doesnotexist').status_code,422)
        for data in ({'ids':[],'action':'delete'},{'ids':[ids[0]]*2,'action':'delete'},{'ids':ids,'action':'move'},{'ids':[ids[0]]*501,'action':'delete'}):
            self.assertEqual(self.client.post('/api/bookmark-tools/bulk',json=data,headers=HEADERS).status_code,422)

    def test_bulk_delete_restores_selected_items_and_preserves_unselected_links(self):
        self.setup_owner();links=self.links();ids=[link['id'] for link in links[:2]]
        result=self.bulk(ids,'delete');self.assertEqual(result.status_code,200,result.text)
        self.assertEqual(len(self.links()),len(links)-2)
        self.assertEqual(self.client.post('/api/trash/'+result.json()['undo_id']+'/restore',headers=HEADERS).status_code,200)
        self.assertEqual({link['id'] for link in self.links()},{link['id'] for link in links})

    def test_duplicate_report_uses_shared_current_url_and_prefers_favorite_keeper(self):
        self.setup_owner();link=self.links()[0]
        duplicate=self.client.post('/api/bookmarks',json={'category_id':link['category_id'],'name':'Alias','url':link['url']},headers=HEADERS).json()
        self.client.put('/api/bookmark-tools/'+duplicate['id']+'/favorite',json={'favorite':True},headers=HEADERS)
        groups=self.client.get('/api/bookmark-tools/duplicates').json()
        group=next(group for group in groups if any(row['id']==link['id'] for row in group['bookmarks']))
        self.assertEqual(group['bookmarks'][0]['id'],duplicate['id'])
        with SessionLocal.begin() as db:
            managed=SharedLink(name='Moved',url='https://changed.test/',icon='world',source_name='Fixture',published=True)
            db.add(managed);db.flush();db.add(SharedPlacement(bookmark_id=duplicate['id'],link_id=managed.id))
        self.assertEqual(self.client.get('/api/bookmark-tools/duplicates').json(),[])

    def test_backup_preserves_favorites_and_preferences_and_undo_restores_prior_preferences(self):
        self.setup_owner();link=self.links()[0]
        self.client.put('/api/bookmark-tools/'+link['id']+'/favorite',json={'favorite':True},headers=HEADERS)
        self.client.put('/api/account/preferences',json={'animation_mode':'on','search_engine':'g'},headers=HEADERS)
        document=self.client.post('/api/backups/export',json={},headers=HEADERS).json()
        self.assertEqual(document['preferences']['animation_mode'],'on');self.assertTrue(document['tabs'][0]['categories'][0]['links'][0]['favorite'])
        self.client.put('/api/bookmark-tools/'+link['id']+'/favorite',json={'favorite':False},headers=HEADERS)
        self.client.put('/api/account/preferences',json={'search_engine':'y'},headers=HEADERS)
        staged=self.client.post('/api/backups/import-preview',json={'document':document},headers=HEADERS).json()
        restored=self.client.post('/api/backups/import',json={'preview_id':staged['preview_id'],'mode':'replace'},headers=HEADERS)
        self.assertEqual(restored.status_code,200,restored.text)
        self.assertEqual(self.portal()['animationMode'],'on');self.assertEqual(self.portal()['search']['default'],'g');self.assertTrue(self.links()[0]['favorite'])
        self.client.post('/api/bookmark-tools/'+self.links()[0]['id']+'/visit',headers=HEADERS)
        undo=self.client.post('/api/trash/'+restored.json()['undo_id']+'/restore',headers=HEADERS);self.assertEqual(undo.status_code,200,undo.text)
        self.assertEqual(self.portal()['search']['default'],'y');self.assertFalse(self.links()[0]['favorite'])

    def test_metadata_is_authenticated_bounded_and_private_addresses_fall_back_without_connecting(self):
        self.setup_owner()
        with patch('app.services.bookmark_metadata.socket.create_connection') as connect:
            response=self.client.post('/api/bookmark-tools/preview',json={'url':'http://127.0.0.1:8000/'},headers=HEADERS)
            self.assertEqual(response.status_code,200,response.text);self.assertFalse(response.json()['resolved']);connect.assert_not_called()
        with patch('app.api.bookmark_tools.preview',return_value={'name':'Preview','icon':'world'}) as preview:
            for _ in range(19):self.assertEqual(self.client.post('/api/bookmark-tools/preview',json={'url':'https://github.com/'},headers=HEADERS).status_code,200)
            self.assertEqual(self.client.post('/api/bookmark-tools/preview',json={'url':'https://github.com/'},headers=HEADERS).status_code,429)
            self.assertEqual(preview.call_count,19)
        for url in ('file:///etc/passwd','https://user:password@example.com/'):
            self.assertEqual(self.client.post('/api/bookmark-tools/preview',json={'url':url},headers=HEADERS).status_code,422)
        self.assertEqual(self.client.post('/api/bookmark-tools/preview',json={'url':'https://example.com/'}).status_code,403)
        self.assertEqual(TestClient(app).post('/api/bookmark-tools/preview',json={'url':'https://example.com/'},headers=HEADERS).status_code,401)

    def test_additive_favorite_migration_keeps_existing_bookmarks(self):
        self.setup_owner();links=self.links()
        with engine.begin() as connection:connection.execute(text('ALTER TABLE dock_bookmarks DROP COLUMN favorite'))
        migrate();migrate()
        self.assertEqual({link['id'] for link in self.links()},{link['id'] for link in links})
        self.assertTrue(all(link['favorite'] is False for link in self.links()))


class MetadataTransportTests(unittest.TestCase):
    def test_title_parser_and_local_brand_icon(self):
        parser=bookmark_metadata.PageTitle();parser.feed('<title> A &amp; B </title><meta property="og:title" content="Portal &amp; Docs">')
        self.assertEqual(parser.title,'Portal & Docs')
        parser.feed('<meta property><meta property="og:title">')
        self.assertEqual(parser.title,'A & B')
        self.assertEqual(bookmark_metadata.suggest_icon('https://www.youtube.com/'),'simple-icons:youtube')
        self.assertEqual(bookmark_metadata.suggest_icon('http://192.168.1.2/'),'world')

    def test_public_get_is_pinned_credential_free_bounded_and_redirect_to_private_is_rejected(self):
        response=MagicMock(status=200)
        response.getheader.side_effect=lambda name,default='': 'text/html; charset=utf-8' if name=='Content-Type' else default
        response.read.return_value=b'<title>Fixture title</title>'
        connection=MagicMock();connection.getresponse.return_value=response
        with patch('app.services.bookmark_metadata.safe_addresses',return_value=['93.184.216.34']),patch('app.services.bookmark_metadata.socket.create_connection') as connect,patch('app.services.bookmark_metadata.http.client.HTTPConnection',return_value=connection):
            self.assertEqual(bookmark_metadata.public_title('http://public.test/page?q=one'),'Fixture title')
            self.assertEqual(connect.call_args.args[0],('93.184.216.34',80));response.read.assert_called_once_with(131072)
            headers={call.args[0] for call in connection.putheader.call_args_list};self.assertNotIn('Authorization',headers);self.assertNotIn('Cookie',headers)
        response.status=302;response.getheader.side_effect=lambda name,default='':'http://127.0.0.1/secret' if name=='Location' else default
        with patch('app.services.bookmark_metadata.safe_addresses',side_effect=[['93.184.216.34'],ValueError('private')]),patch('app.services.bookmark_metadata.socket.create_connection') as connect,patch('app.services.bookmark_metadata.http.client.HTTPConnection',return_value=connection):
            with self.assertRaises(ValueError):bookmark_metadata.public_title('http://public.test/')
            self.assertEqual(connect.call_count,1)
