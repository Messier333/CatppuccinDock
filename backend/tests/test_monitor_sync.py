import ssl,time,unittest
from unittest.mock import patch
from fastapi import HTTPException
import test_auth as legacy
from test_auth import HEADERS
from app.db.models import ProxySync,ServiceMonitor
from app.db.session import SessionLocal
from app.services import monitoring

class MonitoringAndSync(unittest.TestCase):
    setUp=legacy.AuthenticationTests.setUp
    tearDown=legacy.AuthenticationTests.tearDown
    setup_owner=legacy.AuthenticationTests.setup_owner
    def test_outbound_http_transport_uses_pinned_socket_and_modern_tls(self):
        connection=monitoring.pinned_http_connection()
        self.addCleanup(connection.close)
        self.assertEqual((connection.host,connection.port),('192.0.2.1',1))
        self.assertEqual(monitoring.secure_tls_context().minimum_version,ssl.TLSVersion.TLSv1_2)

    def test_classification_dns_policy_and_no_rebinding(self):
        self.assertEqual(monitoring.classify(200)[0],'up')
        self.assertEqual(monitoring.classify(401)[0],'up')
        self.assertEqual(monitoring.classify(403)[0],'up')
        self.assertEqual(monitoring.classify(302,'https://auth.test/if/flow/default-authentication-flow/')[0],'up')
        self.assertEqual(monitoring.classify(502)[0],'down')
        def dns(address):return [(2,1,6,'',(address,443))]
        for address in ('127.0.0.1','169.254.169.254','0.0.0.0','224.0.0.1','::1','::ffff:127.0.0.1'):
            with patch('app.services.monitoring.socket.getaddrinfo',return_value=dns(address)):
                with self.assertRaises(ValueError,msg=address):monitoring.safe_addresses('test',443,True)
        with patch('app.services.monitoring.socket.getaddrinfo',return_value=dns('192.168.1.9')):
            with self.assertRaises(ValueError):monitoring.safe_addresses('test',443,False)
            self.assertEqual(monitoring.safe_addresses('test',443,True),['192.168.1.9'])
        with patch('app.services.monitoring.socket.getaddrinfo',return_value=dns('8.8.8.8')+dns('127.0.0.1')):
            with self.assertRaises(ValueError):monitoring.safe_addresses('test',443,True)
    def test_monitor_manual_check_db_cache_and_member_cannot_probe(self):
        self.setup_owner()
        self.client.post('/api/admin/users',json={'username':'member','password':'a-member-password'},headers=HEADERS)
        from fastapi.testclient import TestClient
        from app.main import app
        member=TestClient(app);member.post('/api/auth/login',json={'username':'member','password':'a-member-password'},headers=HEADERS)
        tab=member.get('/api/portal').json()['tabs'][0]
        link=member.post('/api/bookmarks',json={'name':'Service','url':'https://service.test','category_id':tab['categories'][0]['id']},headers=HEADERS).json()
        result=self.client.post('/api/admin/monitors',json={'name':'Service','link_url':'https://service.test','check_url':'http://192.168.1.2/health','allow_private':True},headers=HEADERS)
        self.assertEqual(result.status_code,200,result.text);mid=result.json()['id']
        self.assertEqual(member.post('/api/admin/monitors/'+mid+'/check',headers=HEADERS).status_code,403)
        with patch('app.services.monitoring.check_url',return_value={'state':'up','http_status':401,'detail':'인증 필요'}) as check:
            result=self.client.post('/api/admin/monitors/'+mid+'/check',headers=HEADERS)
            self.assertEqual(result.status_code,200,result.text);self.assertEqual(result.json()['state'],'up');check.assert_called_once()
        status=member.get('/api/bookmark-status').json();self.assertEqual(status[link['id']]['state'],'up')
        self.assertNotIn('192.168.1.2',str(status))
        with SessionLocal() as db:self.assertGreater(db.get(ServiceMonitor,mid).next_check,time.time()+86000)
        with patch('app.services.monitoring.check_url') as check:monitoring.run_batch([mid]);check.assert_not_called()
    def test_proxy_change_detection_does_not_publish_without_selected_approval(self):
        self.setup_owner()
        source=self.client.post('/api/admin/proxy-sources',json={'name':'Proxy','provider':'npm','base_url':'https://proxy.test','token':'private-api-token'},headers=HEADERS).json()
        prefix='/api/admin/proxy-sources/'+source['id']+'/sync'
        self.assertEqual(self.client.put(prefix,json={'enabled':True,'interval':300},headers=HEADERS).status_code,200)
        with patch('app.services.proxy_sync.fetch_hosts',return_value=[{'domain_names':['one.test','two.test'],'certificate_id':1}]):
            result=self.client.post(prefix+'/check',headers=HEADERS)
        self.assertEqual(result.status_code,200,result.text);current=result.json();self.assertEqual(len(current['changes']),2)
        self.assertEqual(self.client.get('/api/library').json(),[])
        selected=current['changes'][0]
        result=self.client.post(prefix+'/review',json={'revision':current['revision'],'change_ids':[selected['id']]},headers=HEADERS)
        self.assertEqual(result.status_code,200,result.text);self.assertEqual(len(self.client.get('/api/library').json()),1)
        current=result.json();self.assertEqual(len(current['changes']),1)
        self.assertEqual(self.client.post(prefix+'/review',json={'revision':'stale','change_ids':[current['changes'][0]['id']]},headers=HEADERS).status_code,409)
        with SessionLocal.begin() as db:db.get(ProxySync,source['id']).checked_at=time.time()-20
        with patch('app.services.proxy_sync.fetch_hosts',return_value=[]):current=self.client.post(prefix+'/check',headers=HEADERS).json()
        self.assertEqual(len(current['changes']),1);self.assertEqual(current['changes'][0]['kind'],'removed')
        self.assertEqual(len(self.client.get('/api/library').json()),1)
        result=self.client.post(prefix+'/review',json={'revision':current['revision'],'change_ids':[current['changes'][0]['id']]},headers=HEADERS)
        self.assertEqual(result.status_code,200,result.text);self.assertEqual(self.client.get('/api/library').json(),[])
    def test_proxy_api_failure_never_means_remove_all_and_configuration_revision_invalidates(self):
        self.setup_owner()
        source=self.client.post('/api/admin/proxy-sources',json={'name':'Proxy','provider':'npm','base_url':'https://proxy.test','token':'private-api-token'},headers=HEADERS).json()
        prefix='/api/admin/proxy-sources/'+source['id']+'/sync'
        self.client.put(prefix,json={},headers=HEADERS)
        with patch('app.services.proxy_sync.fetch_hosts',side_effect=HTTPException(502,'API 인증 실패')):
            current=self.client.post(prefix+'/check',headers=HEADERS).json()
        self.assertTrue(current['error']);self.assertEqual(current['changes'],[])
        self.assertEqual(self.client.post(prefix+'/review',json={'revision':current['revision'],'change_ids':['missing']},headers=HEADERS).status_code,409)
        self.assertEqual(self.client.delete('/api/admin/proxy-sources/'+source['id'],headers=HEADERS).status_code,200)
        with SessionLocal() as db:self.assertIsNone(db.get(ProxySync,source['id']))
