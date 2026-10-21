import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from fastapi.testclient import TestClient
from sqlalchemy import func, select
import test_auth as legacy_tests
from test_auth import HEADERS
from app.db.models import Bookmark, SharedLink, SharedPlacement
from app.db.session import SessionLocal
from app.main import app
from app.services.audit import configure_audit

class LibraryTests(unittest.TestCase):
    setUp = legacy_tests.AuthenticationTests.setUp
    tearDown = legacy_tests.AuthenticationTests.tearDown
    setup_owner = legacy_tests.AuthenticationTests.setup_owner

    def fixtures(self):
        self.setup_owner()
        self.client.post('/api/admin/users', json={'username':'member','password':'a-member-password'},headers=HEADERS)
        self.member=TestClient(app)
        self.member.post('/api/auth/login',json={'username':'member','password':'a-member-password'},headers=HEADERS)
        self.tab=self.member.get('/api/portal').json()['tabs'][0]
        self.category=self.tab['categories'][0]
        self.source=self.client.post('/api/admin/proxy-sources',json={'name':'Home proxy','provider':'npm','base_url':'http://192.168.1.2:81','token':'private-source-token'},headers=HEADERS).json()
        return self.publish()

    def publish(self):
        with patch('app.api.proxy.fetch_hosts',return_value=[{'domain_names':['public.example.test','private.example.test'],'certificate_id':1}]):
            preview=self.client.post('/api/admin/proxy-sources/'+self.source['id']+'/preview',json={},headers=HEADERS).json()
        result=self.client.post('/api/admin/proxy-sources/'+self.source['id']+'/import',json={'preview_id':preview['preview_id'],'entry_ids':['0'],'destination':'library'},headers=HEADERS)
        self.assertEqual(result.status_code,200,result.text)
        return self.client.get('/api/admin/library').json()[0]

    def add(self,link):
        result=self.member.post('/api/library/'+link['id']+'/add',json={'category_id':self.category['id']},headers=HEADERS)
        self.assertEqual(result.status_code,200,result.text)
        return result.json()['id']

    def published(self,link,value):
        result=self.client.put('/api/admin/library/'+link['id'],json={'name':link['name'],'icon':'simple-icons:docker','published':value},headers=HEADERS)
        self.assertEqual(result.status_code,200,result.text)

    def test_selected_links_only_no_source_details_or_automatic_placements(self):
        link=self.fixtures()
        result=self.member.get('/api/library')
        self.assertEqual([row['url'] for row in result.json()],['https://public.example.test/'])
        for private in ('private.example.test','192.168.1.2','private-source-token','base_url','token_encrypted'):
            self.assertNotIn(private,result.text)
        self.assertFalse(result.json()[0]['added'])
        with SessionLocal() as db:
            self.assertEqual(db.scalar(select(func.count()).select_from(SharedPlacement)),0)
            self.assertFalse(db.scalar(select(Bookmark).where(Bookmark.url==link['url'])))

    def test_member_add_ownership_duplicates_and_admin_only_publication(self):
        link=self.fixtures()
        category=self.client.get('/api/portal').json()['tabs'][0]['categories'][0]['id']
        path='/api/library/'+link['id']+'/add'
        self.assertEqual(self.member.post(path,json={'category_id':category},headers=HEADERS).status_code,404)
        bookmark=self.add(link)
        self.assertTrue(self.member.get('/api/bookmarks/'+bookmark).json()['managed'])
        self.assertEqual(self.client.get('/api/bookmarks/'+bookmark).status_code,404)
        self.assertTrue(self.member.get('/api/library').json()[0]['added'])
        self.assertEqual(self.member.post(path,json={'category_id':self.category['id']},headers=HEADERS).status_code,409)
        self.assertEqual(self.member.post(path,json={'category_id':self.category['id']}).status_code,403)
        for method,path,data in [('GET','/api/admin/library',None),('PUT','/api/admin/library/'+link['id'],{'name':'Hacked','published':True}),('GET','/api/admin/proxy-sources/providers',None)]:
            self.assertEqual(self.member.request(method,path,json=data,headers=HEADERS).status_code,403)
        self.assertEqual(TestClient(app).get('/api/library').status_code,401)

    def test_revocation_hides_subscriptions_and_republishing_restores(self):
        link=self.fixtures()
        bookmark=self.add(link)
        self.published(link,False)
        self.assertEqual(self.member.get('/api/library').json(),[])
        self.assertEqual(self.member.get('/api/bookmarks/'+bookmark).status_code,404)
        entries=[entry for tab in self.member.get('/api/portal').json()['tabs'] for category in tab['categories'] for entry in category['links']]
        self.assertNotIn(bookmark,[entry['id'] for entry in entries])
        self.assertEqual(self.member.post('/api/library/'+link['id']+'/add',json={'category_id':self.category['id']},headers=HEADERS).status_code,404)
        self.published(link,True)
        self.assertEqual(self.member.get('/api/bookmarks/'+bookmark).status_code,200)

    def test_personal_icon_allowed_shared_url_change_denied(self):
        link=self.fixtures()
        bookmark=self.add(link)
        data={'category_id':self.category['id'],'name':'My Docker','url':link['url'],'icon':'simple-icons:docker','icon_color':'#ff0000'}
        path='/api/bookmarks/'+bookmark
        self.assertEqual(self.member.put(path,json=data,headers=HEADERS).status_code,200)
        self.assertEqual(self.member.get(path).json()['icon'],'simple-icons:docker')
        self.assertEqual(self.member.put(path,json={**data,'url':'https://other.test'},headers=HEADERS).status_code,409)
        self.published(link,False)
        self.assertEqual(self.member.put(path,json=data,headers=HEADERS).status_code,404)

    def test_category_rename_preserves_subscription_and_delete_cleans_it(self):
        link=self.fixtures()
        bookmark=self.add(link)
        self.assertEqual(self.member.put('/api/categories/'+self.category['id'],json={'name':'Renamed','tab_id':self.tab['id']},headers=HEADERS).status_code,200)
        self.assertTrue(self.member.get('/api/bookmarks/'+bookmark).json()['managed'])
        self.assertEqual(self.member.delete('/api/categories/'+self.category['id'],headers=HEADERS).status_code,200)
        with SessionLocal() as db:
            self.assertIsNone(db.get(SharedPlacement,bookmark))
            self.assertIsNotNone(db.get(SharedLink,link['id']))

    def test_bookmark_and_tab_delete_cleanup_allow_readd(self):
        link=self.fixtures()
        bookmark=self.add(link)
        self.assertEqual(self.member.delete('/api/bookmarks/'+bookmark,headers=HEADERS).status_code,200)
        bookmark=self.add(link)
        self.assertEqual(self.member.delete('/api/tabs/'+self.tab['id'],headers=HEADERS).status_code,200)
        with SessionLocal() as db: self.assertIsNone(db.get(SharedPlacement,bookmark))

    def test_reimport_no_duplicate_reactivation_and_source_delete(self):
        link=self.fixtures()
        self.publish()
        self.published(link,False)
        self.publish()
        links=self.member.get('/api/library').json()
        self.assertEqual(len(links),1)
        self.assertEqual(links[0]['icon'],'simple-icons:docker')
        bookmark=self.add(link)
        self.assertEqual(self.client.delete('/api/admin/proxy-sources/'+self.source['id'],headers=HEADERS).status_code,200)
        self.assertEqual(self.member.get('/api/bookmarks/'+bookmark).status_code,200)
        with SessionLocal() as db: self.assertIsNone(db.get(SharedLink,link['id']).source_id)

    def test_independent_private_bookmark_is_not_revoked(self):
        link=self.fixtures()
        result=self.member.post('/api/bookmarks',json={'category_id':self.category['id'],'name':'My own link','url':link['url']},headers=HEADERS)
        self.assertEqual(result.status_code,200)
        self.published(link,False)
        self.assertEqual(self.member.get('/api/bookmarks/'+result.json()['id']).status_code,200)

class IconsAuditTests(unittest.TestCase):
    setUp=legacy_tests.AuthenticationTests.setUp
    tearDown=legacy_tests.AuthenticationTests.tearDown
    setup_owner=legacy_tests.AuthenticationTests.setup_owner

    def test_icon_browse_search_pagination_and_local_svg(self):
        self.assertEqual(self.client.get('/api/icons/collections').status_code,401)
        self.setup_owner()
        collections=self.client.get('/api/icons/collections').json()
        self.assertEqual(len(collections),3)
        self.assertGreater(sum(row['total'] for row in collections),17000)
        first=self.client.get('/api/icons?collection=tabler').json()
        second=self.client.get('/api/icons?collection=tabler&offset=48').json()
        self.assertEqual(len(first['icons']),48)
        self.assertTrue(set(first['icons']).isdisjoint(second['icons']))
        self.assertIn('simple-icons:docker',self.client.get('/api/icons?collection=simple-icons&q=docker').json()['icons'])
        self.assertGreater(self.client.get('/api/icons',params={'collection':'tabler','q':'서버'}).json()['total'],0)
        svg=self.client.get('/api/icons/simple-icons:docker.svg')
        self.assertEqual(svg.status_code,200)
        self.assertIn('<svg',svg.text)
        self.assertIn('image/svg+xml',svg.headers['content-type'])
        self.assertEqual(svg.headers['cache-control'],'private, max-age=86400')
        self.assertIn('sandbox',svg.headers['content-security-policy'])

    def test_icon_validation_and_bookmark_persistence(self):
        self.setup_owner()
        category=self.client.get('/api/portal').json()['tabs'][0]['categories'][0]['id']
        data={'category_id':category,'name':'Docker','url':'https://docker.test','icon':'simple-icons:docker'}
        result=self.client.post('/api/bookmarks',json=data,headers=HEADERS)
        self.assertEqual(result.status_code,200,result.text)
        self.assertEqual(self.client.get('/api/bookmarks/'+result.json()['id']).json()['icon'],'simple-icons:docker')
        for icon in ('evil:docker','simple-icons:no-such-icon-zzzzz','https://attacker.test/x.svg','<svg>','tabler:../bad'):
            self.assertEqual(self.client.post('/api/bookmarks',json={**data,'icon':icon},headers=HEADERS).status_code,422)
        self.assertEqual(self.client.get('/api/icons?collection=unknown').status_code,422)

    def test_failure_logs_real_ip_without_credentials_and_normal_401_is_not_failure(self):
        self.setup_owner()
        with self.assertLogs('catppuccindock.security',level='WARNING') as captured:
            self.client.post('/api/auth/login',json={'username':'unregistered-person','password':'never-log-this-password'},headers={**HEADERS,'X-Real-IP':'198.51.100.23'})
        log='\n'.join(captured.output)
        self.assertIn('failure client=198.51.100.23 scope=login status=401',log)
        self.assertNotIn('never-log-this-password',log)
        self.assertNotIn('unregistered-person',log)
        with self.assertNoLogs('catppuccindock.security',level='WARNING'): TestClient(app).get('/api/portal')
        with self.assertLogs('catppuccindock.security',level='WARNING') as captured:
            self.client.post('/api/auth/login',json={'username':'no','password':'bad'},headers={**HEADERS,'X-Real-IP':'198.51.100.1 fake scope=login'})
        self.assertIn('client=unknown','\n'.join(captured.output))

    def test_persistent_file_records_ipv6_failure(self):
        self.setup_owner()
        with tempfile.TemporaryDirectory() as directory:
            target=Path(directory)/'auth.log'
            with patch.dict(os.environ,{'AUTH_LOG_PATH':str(target)}):
                configure_audit()
                self.client.post('/api/auth/login',json={'username':'no','password':'bad'},headers={**HEADERS,'X-Real-IP':'2001:db8::1'})
                self.assertIn('catppuccindock-auth failure client=2001:db8::1 scope=login status=401',target.read_text())
            configure_audit()
