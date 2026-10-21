import time,unittest
from unittest.mock import patch
from fastapi.testclient import TestClient
from sqlalchemy import select,func,delete
import test_auth as legacy
from test_auth import HEADERS
from app.main import app
from app.db.models import ServiceMonitor,SharedLink,SharedPlacement
from app.db.session import SessionLocal
from app.services import monitoring

class MonitorBulkTests(unittest.TestCase):
    setUp=legacy.AuthenticationTests.setUp
    tearDown=legacy.AuthenticationTests.tearDown
    setup_owner=legacy.AuthenticationTests.setup_owner
    def links(self):return self.client.get('/api/portal').json()['tabs'][0]['categories'][0]['links']
    def total(self):
        with SessionLocal() as db:return db.scalar(select(func.count()).select_from(ServiceMonitor))
    def member(self):
        self.client.post('/api/admin/users',json={'username':'bulk-member','password':'a-member-password'},headers=HEADERS)
        client=TestClient(app);client.post('/api/auth/login',json={'username':'bulk-member','password':'a-member-password'},headers=HEADERS)
        return client
    def test_bulk_registration_deduplicates_urls_and_preserves_existing_custom_checks(self):
        self.setup_owner();links=self.links()
        existing=self.client.post('/api/admin/monitors',json={'name':'Custom','link_url':links[0]['url'],'check_url':'https://health.test/custom','interval':900,'enabled':False},headers=HEADERS).json()
        alias=self.client.post('/api/bookmarks',json={'name':'Alias','url':links[1]['url'],'category_id':links[1]['category_id']},headers=HEADERS).json()
        with patch('app.services.monitoring.check_url') as check:
            result=self.client.post('/api/admin/monitors/bulk',json={'bookmark_ids':[links[0]['id'],links[1]['id'],alias['id'],links[1]['id']],'interval':120,'allow_private':True},headers=HEADERS)
            self.assertEqual(result.status_code,200,result.text);self.assertEqual(result.json(),{'added':1,'duplicates':3});check.assert_not_called()
        rows=self.client.get('/api/admin/monitors').json();self.assertEqual(len(rows),2)
        old=next(row for row in rows if row['id']==existing['id']);self.assertEqual(old['check_url'],'https://health.test/custom');self.assertFalse(old['enabled']);self.assertEqual(old['interval'],900)
        new=next(row for row in rows if row['id']!=existing['id']);self.assertEqual(new['link_url'],new['check_url']);self.assertEqual(new['interval'],120);self.assertTrue(new['allow_private']);self.assertTrue(new['enabled'])
    def test_ownership_role_and_missing_ids_do_not_partially_register(self):
        self.setup_owner();member=self.member();own=self.links()[0]['id'];foreign=member.get('/api/portal').json()['tabs'][0]['categories'][0]['links'][0]['id']
        for bad in (foreign,'missing'):
            result=self.client.post('/api/admin/monitors/bulk',json={'bookmark_ids':[own,bad]},headers=HEADERS);self.assertEqual(result.status_code,409,result.text);self.assertEqual(self.total(),0)
        self.assertEqual(member.post('/api/admin/monitors/bulk',json={'bookmark_ids':[foreign]},headers=HEADERS).status_code,403)
        self.assertEqual(self.client.post('/api/admin/monitors/bulk',json={'bookmark_ids':[own]}).status_code,403)
        self.assertEqual(TestClient(app).post('/api/admin/monitors/bulk',json={'bookmark_ids':[own]},headers=HEADERS).status_code,401)
        for ids in ([],[own]*201):self.assertEqual(self.client.post('/api/admin/monitors/bulk',json={'bookmark_ids':ids},headers=HEADERS).status_code,422)
    def test_invalid_credentials_and_capacity_errors_are_atomic(self):
        self.setup_owner();links=self.links()
        invalid=self.client.post('/api/bookmarks',json={'name':'Credentials','url':'https://user:password@private.test','category_id':links[0]['category_id']},headers=HEADERS).json()
        result=self.client.post('/api/admin/monitors/bulk',json={'bookmark_ids':[links[0]['id'],invalid['id']]},headers=HEADERS);self.assertEqual(result.status_code,422,result.text);self.assertEqual(self.total(),0)
        with SessionLocal.begin() as db:
            db.add_all(ServiceMonitor(name=f'Monitor {i}',link_url=f'https://capacity-{i}.test/',check_url=f'https://capacity-{i}.test/',enabled=False,revision=str(i)) for i in range(999))
        result=self.client.post('/api/admin/monitors/bulk',json={'bookmark_ids':[row['id'] for row in links]},headers=HEADERS);self.assertEqual(result.status_code,409,result.text);self.assertEqual(self.total(),999)
    def test_bulk_uses_current_shared_url_and_rejects_unpublished_links(self):
        self.setup_owner();link=self.links()[0]
        with SessionLocal.begin() as db:
            shared=SharedLink(name='Managed',url='https://updated-shared.test/',icon='world',icon_color='auto',source_name='Fixture',published=True)
            db.add(shared);db.flush();sid=shared.id;db.add(SharedPlacement(bookmark_id=link['id'],link_id=sid))
        result=self.client.post('/api/admin/monitors/bulk',json={'bookmark_ids':[link['id']]},headers=HEADERS);self.assertEqual(result.status_code,200,result.text)
        self.assertEqual(self.client.get('/api/admin/monitors').json()[0]['check_url'],'https://updated-shared.test/')
        with SessionLocal.begin() as db:db.get(SharedLink,sid).published=False;db.execute(delete(ServiceMonitor))
        self.assertEqual(self.client.post('/api/admin/monitors/bulk',json={'bookmark_ids':[link['id']]},headers=HEADERS).status_code,409);self.assertEqual(self.total(),0)
    def test_check_all_only_queues_enabled_eligible_targets_and_has_global_cooldown(self):
        self.setup_owner();now=time.time()
        with SessionLocal.begin() as db:
            for name,enabled,checked,status in (('up',True,now-30,200),('auth',True,now-7200,403),('recent',True,now,200),('off',False,None,None)):
                db.add(ServiceMonitor(name=name,link_url=f'https://{name}.test/',check_url=f'https://{name}.test/',enabled=enabled,checked_at=checked,http_status=status,state='up' if checked else 'pending',next_check=now+86400,revision=name))
        with patch('app.api.monitoring.run_batch') as job:
            response=self.client.post('/api/admin/monitors/check-all',headers=HEADERS)
            self.assertEqual(response.status_code,200,response.text);result=response.json();self.assertEqual(len(result['queued_ids']),2);self.assertEqual(result['skipped'],1);job.assert_called_once_with(result['queued_ids'])
        with patch('app.services.monitoring.check_url',return_value={'state':'up','http_status':200,'detail':'정상 응답'}):
            for mid in result['queued_ids']:monitoring.run_check(mid)
        rows=self.client.get('/api/admin/monitors').json()
        for row in rows:
            if row['name'] in ('up','auth'):self.assertGreaterEqual(row['checked_at'],result['requested_at'])
            if row['name']=='off':self.assertIsNone(row['checked_at'])
        self.assertEqual(self.client.post('/api/admin/monitors/check-all',headers=HEADERS).status_code,409)
        self.assertEqual(self.client.post('/api/admin/monitors/check-all').status_code,403)
        member=self.member();self.assertEqual(member.post('/api/admin/monitors/check-all',headers=HEADERS).status_code,403)
    def test_authentication_responses_and_existing_auth_cache_are_online(self):
        self.setup_owner();link=self.links()[0]
        for status in (200,302,401,403):self.assertEqual(monitoring.classify(status,'/login')[0],'up')
        for status in (404,500,503):self.assertEqual(monitoring.classify(status)[0],'down')
        with SessionLocal.begin() as db:
            db.add(ServiceMonitor(name='Existing auth',link_url=link['url'],check_url=link['url'],enabled=True,state='auth',http_status=401,checked_at=time.time()-3600,next_check=time.time()+82000,revision='legacy'))
        self.assertEqual(self.client.get('/api/admin/monitors').json()[0]['state'],'up')
        self.assertEqual(self.client.get('/api/bookmark-status').json()[link['id']]['state'],'up')
        with SessionLocal.begin() as db:db.scalar(select(ServiceMonitor)).state='up'
        self.assertEqual(self.client.get('/api/bookmark-status').json()[link['id']]['state'],'up')
