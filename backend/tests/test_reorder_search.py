import unittest
from unittest.mock import AsyncMock, patch

import httpx
from fastapi.testclient import TestClient

import test_auth as legacy_tests
from test_auth import HEADERS
from app.api import search
from app.db.models import SharedLink, SharedPlacement
from app.db.session import SessionLocal
from app.main import app


class ReorderSearchTests(unittest.TestCase):
    tearDown = legacy_tests.AuthenticationTests.tearDown
    setup_owner = legacy_tests.AuthenticationTests.setup_owner

    def setUp(self):
        legacy_tests.AuthenticationTests.setUp(self)
        search.cache.clear(); search.attempts.clear()
        self.setup_owner()

    def portal(self, client=None):
        return (client or self.client).get('/api/portal').json()

    def member(self):
        self.client.post('/api/admin/users', json={'username':'sort-member','password':'a-member-password'}, headers=HEADERS)
        member=TestClient(app)
        member.post('/api/auth/login',json={'username':'sort-member','password':'a-member-password'},headers=HEADERS)
        return member

    def test_tab_category_bookmark_order_persists_atomically(self):
        portal=self.portal()
        tab=portal['tabs'][0]; category=tab['categories'][0]
        for kind, parent, items in [('tabs',None,portal['tabs']),('categories',tab['id'],tab['categories']),('bookmarks',category['id'],category['links'])]:
            ids=[item['id'] for item in reversed(items)]
            result=self.client.post('/api/reorder',json={'kind':kind,'parent_id':parent,'ids':ids},headers=HEADERS)
            self.assertEqual(result.status_code,200,result.text)
            fresh=self.portal()
            actual=fresh['tabs'] if kind=='tabs' else next(item for item in fresh['tabs'] if item['id']==tab['id'])['categories'] if kind=='categories' else next(group for page in fresh['tabs'] for group in page['categories'] if group['id']==category['id'])['links']
            self.assertEqual([item['id'] for item in actual],ids)
            self.assertEqual([item['position'] for item in actual],list(range(len(ids))))

    def test_bad_foreign_duplicate_and_stale_orders_do_not_partially_change_positions(self):
        category=self.portal()['tabs'][0]['categories'][0]
        ids=[item['id'] for item in category['links']]
        data={'kind':'bookmarks','parent_id':category['id'],'ids':list(reversed(ids))}
        other=self.member()
        self.assertEqual(other.post('/api/reorder',json=data,headers=HEADERS).status_code,404)
        for extra,status in [({'ids':ids[:-1]},409),({'ids':[ids[0],ids[0]]},422),({'ids':ids+['foreign-id']},409),({'kind':'unknown'},422),({'parent_id':None},422)]:
            self.assertEqual(self.client.post('/api/reorder',json={**data,**extra},headers=HEADERS).status_code,status)
            self.assertEqual([item['id'] for item in self.portal()['tabs'][0]['categories'][0]['links']],ids)
        self.assertEqual(self.client.post('/api/reorder',json=data).status_code,403)
        self.assertEqual(TestClient(app).post('/api/reorder',json=data,headers=HEADERS).status_code,401)
        own=other.get('/api/portal').json()['tabs'][0]['categories'][0]
        self.assertEqual(other.post('/api/reorder',json={'kind':'bookmarks','parent_id':own['id'],'ids':[item['id'] for item in reversed(own['links'])]},headers=HEADERS).status_code,200)

    def test_hidden_managed_bookmarks_do_not_break_visible_reorder(self):
        category=self.portal()['tabs'][0]['categories'][0]
        hidden=category['links'][0]
        with SessionLocal.begin() as db:
            link=SharedLink(source_name='Test',name='Hidden',url='https://hidden.test/',published=False)
            db.add(link); db.flush()
            db.add(SharedPlacement(bookmark_id=hidden['id'],link_id=link.id))
            link_id=link.id
        visible=self.portal()['tabs'][0]['categories'][0]['links']
        ids=[item['id'] for item in reversed(visible)]
        result=self.client.post('/api/reorder',json={'kind':'bookmarks','parent_id':category['id'],'ids':ids},headers=HEADERS)
        self.assertEqual(result.status_code,200,result.text)
        with SessionLocal.begin() as db: db.get(SharedLink,link_id).published=True
        restored=self.portal()['tabs'][0]['categories'][0]['links']
        self.assertEqual([item['id'] for item in restored],ids+[hidden['id']])

    def test_suggestions_authenticated_post_header_and_private_addresses_stay_local(self):
        self.assertEqual(TestClient(app).post('/api/search/suggestions',json={'query':'docker'},headers=HEADERS).status_code,401)
        self.assertEqual(self.client.post('/api/search/suggestions',json={'query':'docker'}).status_code,403)
        with patch('app.api.search.google_suggestions',new_callable=AsyncMock) as upstream:
            for value in ('x','http://internal.local','192.168.1.9','admin@example.com','localhost','NAS:8090','token?x=secret','word\nattack'):
                result=self.client.post('/api/search/suggestions',json={'query':value},headers=HEADERS)
                self.assertEqual(result.status_code,200,result.text)
                self.assertEqual(result.json()['suggestions'],[])
            upstream.assert_not_awaited()

    def test_suggestions_transient_cache_is_user_scoped_and_failure_is_graceful(self):
        with patch('app.api.search.google_suggestions',new_callable=AsyncMock,return_value=['docker desktop']) as upstream:
            for _ in range(2):
                result=self.client.post('/api/search/suggestions',json={'query':'docker'},headers=HEADERS)
                self.assertEqual(result.json(),{'suggestions':['docker desktop'],'available':True})
            self.assertEqual(upstream.await_count,1)
            self.member().post('/api/search/suggestions',json={'query':'docker'},headers=HEADERS)
            self.assertEqual(upstream.await_count,2)
        with patch('app.api.search.google_suggestions',new_callable=AsyncMock,return_value=None):
            result=self.client.post('/api/search/suggestions',json={'query':'unavailable'},headers=HEADERS)
            self.assertEqual(result.status_code,200)
            self.assertEqual(result.json(),{'suggestions':[],'available':False})
        with patch('app.api.search.google_suggestions',new_callable=AsyncMock,side_effect=TimeoutError):
            self.assertFalse(self.client.post('/api/search/suggestions',json={'query':'timeout'},headers=HEADERS).json()['available'])

    def test_suggestion_budget_does_not_return_failure_status_that_triggers_proxy_bans(self):
        with patch('app.api.search.google_suggestions',new_callable=AsyncMock,return_value=[]) as upstream:
            for index in range(61):
                result=self.client.post('/api/search/suggestions',json={'query':f'query {index}'},headers=HEADERS)
                self.assertEqual(result.status_code,200)
            self.assertFalse(result.json()['available'])
            self.assertEqual(upstream.await_count,60)


class GoogleResponseTests(unittest.IsolatedAsyncioTestCase):
    async def fetch(self, handler):
        original=httpx.AsyncClient
        with patch('app.api.search.httpx.AsyncClient',side_effect=lambda **options:original(transport=httpx.MockTransport(handler),**options)):
            return await search.google_suggestions('docker')

    async def test_fixed_provider_query_and_no_session_forwarding(self):
        def handler(request):
            self.assertEqual(str(request.url.copy_with(query=None)),'https://suggestqueries.google.com/complete/search')
            self.assertEqual(request.url.params['q'],'docker')
            self.assertEqual(request.url.params['client'],'firefox')
            self.assertNotIn('cookie',request.headers)
            self.assertNotIn('authorization',request.headers)
            return httpx.Response(200,json=['docker',['docker desktop','docker desktop','https://private.test',7,'docker 설치']])
        self.assertEqual(await self.fetch(handler),['docker desktop','docker 설치'])

    async def test_upstream_errors_redirects_invalid_and_oversized_json(self):
        for status,payload in [(302,[]),(429,[]),(200,{'error':'wrong'}),(200,['docker','not-a-list'])]:
            self.assertIsNone(await self.fetch(lambda request:httpx.Response(status,json=payload)))
        self.assertIsNone(await self.fetch(lambda request:httpx.Response(200,content=b'x'*65537)))
        self.assertIsNone(await self.fetch(lambda request:httpx.Response(200,text='<html>blocked</html>')))
