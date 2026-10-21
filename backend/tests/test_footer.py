import time
import unittest
from unittest.mock import patch, AsyncMock
from fastapi.testclient import TestClient
import test_auth as legacy
from test_auth import HEADERS
from app.main import app
from app.core.security import cipher
from app.db.models import FooterMetric
from app.db.session import SessionLocal
from app.services import footer, weather

DATA = {'name': 'CPU', 'provider': 'prometheus', 'base_url': 'https://metrics.test', 'query': 'avg(cpu)', 'token': 'private-metric-token', 'unit': '%', 'audience': 'all'}

class FooterTests(unittest.TestCase):
    setUp = legacy.AuthenticationTests.setUp
    tearDown = legacy.AuthenticationTests.tearDown
    setup_owner = legacy.AuthenticationTests.setup_owner

    def member(self):
        self.client.post('/api/admin/users', json={'username':'member','password':'a-member-password'}, headers=HEADERS)
        client = TestClient(app)
        client.post('/api/auth/login',json={'username':'member','password':'a-member-password'},headers=HEADERS)
        return client

    def create(self, **changes):
        response = self.client.post('/api/admin/footer/metrics', json=DATA | changes, headers=HEADERS)
        self.assertEqual(response.status_code,200,response.text)
        return response.json()

    def test_permissions_credentials_and_mandatory_footer_items(self):
        self.setup_owner(); member = self.member()
        row = self.create()
        self.assertNotIn('private-metric-token', str(row))
        self.assertEqual(member.get('/api/admin/footer').status_code,403)
        self.assertEqual(member.post('/api/admin/footer/metrics',json=DATA,headers=HEADERS).status_code,403)
        visible = member.get('/api/footer').json()
        for secret in ('metrics.test','avg(cpu)','private-metric-token','base_url','query'):
            self.assertNotIn(secret,str(visible))
        order = self.client.get('/api/admin/footer').json()['order']
        self.assertEqual(self.client.put('/api/admin/footer',json={'order':order,'hidden':['logout']},headers=HEADERS).status_code,422)
        self.assertEqual(self.client.put('/api/admin/footer',json={'order':order,'hidden':['clock']},headers=HEADERS).status_code,200)
        self.assertIn('clock',member.get('/api/footer').json()['hidden'])
        own = visible['order'][::-1]
        self.assertEqual(member.put('/api/footer/order',json={'order':own},headers=HEADERS).status_code,200)
        self.assertEqual(member.get('/api/footer').json()['order'],own)
        self.assertNotEqual(self.client.get('/api/footer').json()['order'],own)
        self.assertEqual(member.put('/api/footer/order',json={'order':own+['arbitrary']},headers=HEADERS).status_code,409)
        self.assertEqual(member.put('/api/footer/order',json={'order':own,'hidden':['settings']},headers=HEADERS).status_code,422)
        self.assertEqual(member.delete('/api/footer/order',headers=HEADERS).status_code,200)
        self.client.put('/api/admin/footer/metrics/'+row['id'],json=DATA|{'audience':'admin','token':None},headers=HEADERS)
        self.assertEqual(member.get('/api/footer').json()['metrics'],[])

    def test_edit_button_is_configurable_and_old_layouts_preserve_their_order(self):
        self.setup_owner()
        from app.db.models import Setting
        previous=['clock','theme','fastlink','tabs','weather','settings','logout']
        with SessionLocal.begin() as db:
            db.add(Setting(key='footer',value={'order':previous,'hidden':['weather']}))
            db.add(Setting(key='footer:1',value={'order':previous[::-1]}))
        common=self.client.get('/api/admin/footer').json()
        self.assertEqual(common['order'],previous+['edit'])
        own=self.client.get('/api/footer').json()
        self.assertEqual(own['order'],previous[::-1]+['edit'])
        self.assertEqual(self.client.put('/api/admin/footer',json={'order':common['order'],'hidden':['weather','edit']},headers=HEADERS).status_code,200)
        self.assertIn('edit',self.client.get('/api/footer').json()['hidden'])
        self.assertEqual(self.client.put('/api/admin/footer',json={'order':common['order'],'hidden':['settings']},headers=HEADERS).status_code,422)

    def test_token_retention_origin_change_removal_and_query_validation(self):
        self.setup_owner(); row=self.create()
        with SessionLocal() as db:
            stored=db.get(FooterMetric,row['id']).token_encrypted
            self.assertNotIn('private-metric-token',stored)
            self.assertEqual(cipher().decrypt(stored.encode()).decode(),'private-metric-token')
        for change,has_token in (({'token':None},True),({'token':None,'base_url':'https://different.test'},False),({'token':'next-token'},True),({'token':None,'clear_token':True},False)):
            result=self.client.put('/api/admin/footer/metrics/'+row['id'],json=DATA|change,headers=HEADERS)
            self.assertEqual(result.status_code,200,result.text);self.assertEqual(result.json()['has_token'],has_token)
        for change in ({'query':''},{'provider':'grafana','datasource_uid':''},{'provider':'kuma','monitor_id':''},{'token':'bad\r\nHeader: secret'},{'base_url':'https://user:pass@metrics.test'},{'display':'status'}):
            self.assertEqual(self.client.post('/api/admin/footer/metrics',json=DATA|change,headers=HEADERS).status_code,422)

    def test_adapters_one_series_nan_grafana_prefix_and_kuma_order(self):
        config=DATA|{'allow_private':False,'window':3600,'datasource_uid':'prom-uid'}
        matrix={'status':'success','data':{'result':[{'values':[[1,'2'],[2,'NaN'],[3,'4.5']]}]}}
        with patch('app.services.footer.json_request',return_value=matrix) as request:
            result=footer.collect(config,'token')
            self.assertEqual(result['points'],[2,None,4.5]);self.assertEqual(result['value'],4.5)
            self.assertIn('/api/v1/query_range?',request.call_args.args[0]);self.assertIn('query=avg%28cpu%29',request.call_args.args[0])
            footer.collect(config|{'provider':'grafana','base_url':'https://grafana.test/grafana'},'token')
            self.assertIn('/grafana/api/datasources/proxy/uid/prom-uid/api/v1/query_range?',request.call_args.args[0])
        with patch('app.services.footer.json_request',return_value={'status':'success','data':{'result':[{},{}]}}):
            with self.assertRaises(ValueError):footer.collect(config,'')
        kuma={'heartbeatList':{'1':[{'time':'2026-10-20 12:02','status':0,'ping':None},{'time':'2026-10-20 12:01','status':1,'ping':8}]},'uptimeList':{'1_24':.995}}
        config|={'provider':'kuma','slug':'home','monitor_id':'1','metric':'status'}
        with patch('app.services.footer.json_request',return_value=kuma):
            result=footer.collect(config,'');self.assertEqual(result['state'],'down');self.assertEqual(result['points'],[1,0])
            self.assertEqual(footer.collect(config|{'metric':'uptime'},'')['value'],99.5)
            self.assertFalse(footer.collect(config|{'metric':'latency'},'')['available'])

    def test_polling_cache_auth_backoff_and_stale_configuration(self):
        self.setup_owner();row=self.create()
        success={'available':True,'value':50,'points':[45,50],'state':'up'}
        with patch('app.services.footer.collect',return_value=success) as collect:
            footer.run_due();footer.run_due();collect.assert_called_once()
        self.assertEqual(self.client.get('/api/footer').json()['metrics'][0]['result']['value'],50)
        self.assertEqual(self.client.post('/api/admin/footer/metrics/'+row['id']+'/check',headers=HEADERS).status_code,409)
        with SessionLocal.begin() as db:
            metric=db.get(FooterMetric,row['id']);metric.next_check=0;metric.attempted_at=0
        with patch('app.services.footer.collect',side_effect=footer.AuthenticationFailure('upstream-secret')):
            footer.run_due()
        with SessionLocal() as db:
            metric=db.get(FooterMetric,row['id']);self.assertGreater(metric.next_check,time.time()+86000);self.assertNotIn('upstream-secret',str(metric.result))
        with SessionLocal.begin() as db:db.get(FooterMetric,row['id']).next_check=0
        def changed(*args):
            with SessionLocal.begin() as db:db.get(FooterMetric,row['id']).revision='new-revision'
            return success
        with patch('app.services.footer.collect',side_effect=changed):footer.run_due()
        with SessionLocal() as db:self.assertFalse(db.get(FooterMetric,row['id']).result['available'])

    def test_weather_manual_refresh_bypasses_old_cache_but_has_one_minute_budget(self):
        self.setup_owner();weather.cache.clear()
        result={'available':True,'temperature':22,'observed_at':'2026-10-20T12:00','resolved_location':'Seoul'}
        with patch('app.services.weather.fetch_with_retry',new=AsyncMock(return_value=result)) as fetch:
            self.assertEqual(self.client.get('/api/weather').status_code,200)
            self.assertEqual(self.client.post('/api/weather/refresh',headers=HEADERS).status_code,200)
            self.assertEqual(fetch.await_count,1)
            key=next(iter(weather.cache));expiry,saved=weather.cache[key];weather.cache[key]=(expiry-61,saved)
            self.assertEqual(self.client.post('/api/weather/refresh',headers=HEADERS).status_code,200)
            self.assertEqual(fetch.await_count,2)
        self.assertEqual(self.client.post('/api/weather/refresh').status_code,403)
        weather.cache.clear()
