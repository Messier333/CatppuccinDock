"""Private integration, permission revocation, confirmation replay and transport tests."""
import io
import json
import unittest
from copy import deepcopy
from unittest.mock import MagicMock, patch

from fastapi.testclient import TestClient
import test_auth as legacy
from test_auth import HEADERS
from app.main import app
from app.core.security import cipher
from app.db.models import Bookmark, OperationPreview, ServiceIntegration
from app.db.session import SessionLocal
from app.schemas.proxmox import ActionRequest, IntegrationData
from app.services import proxmox
from app.services.proxmox.client import Client, ProxmoxError, permitted
from app.services.proxmox.operations import capabilities, plan

ROOT = '/api/integrations/proxmox'
DATA = {'name': 'Home PVE', 'base_url': 'https://pve.example.test:8006', 'token_id': 'dock@pve!portal', 'token': 'fixture-only-token', 'controls': True}
INVENTORY = [
    {'type': 'node', 'node': 'pve1', 'status': 'online', 'cpu': .25, 'maxcpu': 16, 'mem': 4 * 1024**3, 'maxmem': 16 * 1024**3},
    {'type': 'node', 'node': 'pve2', 'status': 'online', 'cpu': .5, 'maxcpu': 8, 'mem': 8 * 1024**3, 'maxmem': 16 * 1024**3},
    {'type': 'qemu', 'node': 'pve1', 'vmid': 100, 'name': 'media', 'status': 'running', 'maxmem': 4 * 1024**3},
    {'type': 'lxc', 'node': 'pve1', 'vmid': 101, 'name': 'dns', 'status': 'stopped'},
    {'type': 'qemu', 'node': 'pve2', 'vmid': 102, 'name': 'hidden', 'status': 'running'},
    {'type': 'storage', 'node': 'pve1', 'storage': 'local', 'disk': 25, 'maxdisk': 100},
]
PRIVILEGES = ['VM.Audit', 'Sys.Audit', 'Datastore.Audit', 'VM.PowerMgmt', 'VM.Snapshot', 'VM.Snapshot.Rollback', 'VM.Backup', 'VM.Clone', 'VM.Migrate', 'VM.Allocate', 'VM.Config.CPU', 'VM.Config.Memory', 'VM.Config.Options', 'Datastore.AllocateSpace', 'Sys.PowerMgmt']


class FakePVE:
    def __init__(self):
        self.tree = {'/': dict.fromkeys(PRIVILEGES, 1)}
        self.resources = deepcopy(INVENTORY)
        self.calls = []
        self.current = {'status': 'running', 'qmpstatus': 'running'}
        self.task_status = {'status': 'stopped', 'exitstatus': 'OK'}
        self.failure = None

    def request(self, method, path, parameters=None):
        self.calls.append((method, path, parameters))
        if self.failure:
            raise self.failure
        if method == 'GET':
            if path == '/cluster/resources': return deepcopy(self.resources)
            if path == '/access/permissions':
                if parameters and 'path' in parameters:
                    scope = parameters['path']
                    return {scope: {p: 1 for p in PRIVILEGES if permitted(self.tree, scope, p)}}
                return deepcopy(self.tree)
            if path.endswith('/status/current'): return dict(self.current)
            if '/tasks/' in path: return self.task_status
            if path.endswith('/snapshot'): return [{'name': 'current'}, {'name': 'before', 'description': 'fixture', 'snaptime': 1}]
            raise AssertionError(('unexpected read', path))
        return 'UPID:pve1:00000001:00000001:00000001:qmstart:100:dock@pve!portal:'


class ProxmoxTests(unittest.TestCase):
    setUp = legacy.AuthenticationTests.setUp
    tearDown = legacy.AuthenticationTests.tearDown
    setup_owner = legacy.AuthenticationTests.setup_owner

    def member(self):
        self.client.post('/api/admin/users', json={'username': 'pve-member', 'password': 'a-member-password'}, headers=HEADERS)
        client = TestClient(app)
        client.post('/api/auth/login', json={'username': 'pve-member', 'password': 'a-member-password'}, headers=HEADERS)
        return client

    def create(self, client=None, **changes):
        response = (client or self.client).post(ROOT, json=DATA | changes, headers=HEADERS)
        self.assertEqual(response.status_code, 200, response.text)
        return response.json()

    def release_read(self, integration_id):
        with SessionLocal.begin() as db:
            row = db.get(ServiceIntegration, integration_id)
            row.detail_after = 0

    def preview(self, row, action='shutdown', resource='qemu/100', parameters=None):
        self.release_read(row['id'])
        return self.client.post(ROOT + '/' + row['id'] + '/intents', json={'resource': resource, 'action': action, 'parameters': parameters or {}}, headers=HEADERS)

    def test_owner_isolation_even_from_administrators_and_no_secret_disclosure(self):
        self.setup_owner(); member = self.member()
        own = self.create(); other = self.create(member, name='member-private')
        self.assertNotIn('fixture-only-token', json.dumps(own))
        self.assertEqual(len(member.get(ROOT).json()['integrations']), 1)
        self.assertNotIn(other['id'], self.client.get(ROOT).text)
        for caller, foreign in [(member, own), (self.client, other)]:
            base = ROOT + '/' + foreign['id']
            for method, path, payload in [('post', '/refresh', None), ('get', '/tasks', None), ('get', '/resource?resource=qemu/100', None), ('put', '', DATA), ('delete', '', None), ('put', '/presentation', {k: own['config'][k] for k in ['bookmark_ids', 'metrics', 'sections', 'columns']}), ('post', '/intents', {'resource': 'qemu/100', 'action': 'stop'}), ('post', '/execute', {'intent': 'a' * 48, 'confirmation': '100'}), ('post', '/tasks/foreign/refresh', None)]:
                kwargs = {'headers': HEADERS} | ({'json': payload} if payload is not None else {})
                response = getattr(caller, method)(base + path, **kwargs)
                self.assertEqual(response.status_code, 404, (path, response.text))
        self.assertEqual(TestClient(app).get(ROOT).status_code, 401)
        self.assertEqual(self.client.post(ROOT, json=DATA).status_code, 403)
        with SessionLocal() as db:
            stored = db.get(ServiceIntegration, own['id']).token_encrypted
            self.assertNotIn('fixture-only-token', stored)
            self.assertEqual(cipher().decrypt(stored.encode()).decode(), 'fixture-only-token')

    def test_bindings_and_presentation_are_owned_validated_and_persistent(self):
        self.setup_owner(); member = self.member()
        portal = self.client.get('/api/portal').json()
        bookmark = portal['tabs'][0]['categories'][0]['links'][0]['id']
        own = self.create(bookmark_ids=[bookmark])
        self.assertEqual(member.post(ROOT, json=DATA | {'bookmark_ids': [bookmark]}, headers=HEADERS).status_code, 404)
        self.assertEqual(self.client.post(ROOT, json=DATA | {'bookmark_ids': [bookmark]}, headers=HEADERS).status_code, 409)
        config = {key: own['config'][key] for key in ('bookmark_ids', 'metrics', 'sections', 'columns')}
        config['metrics'] = ['cpu', 'memory']; config['sections'].reverse(); config['sections'][0] |= {'visible': False, 'width': 'half'}
        response = self.client.put(f'{ROOT}/{own["id"]}/presentation', json=config, headers=HEADERS)
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(self.client.get(ROOT).json()['integrations'][0]['config']['sections'], config['sections'])
        for changes in ({'metrics': ['cpu'] * 2}, {'metrics': ['cpu', 'memory', 'storage', 'nodes']}, {'sections': config['sections'][:-1]}, {'columns': ['password']}, {'controls': True}):
            self.assertEqual(self.client.put(f'{ROOT}/{own["id"]}/presentation', json=config | changes, headers=HEADERS).status_code, 422)
        with SessionLocal.begin() as db: db.delete(db.get(Bookmark, bookmark))
        self.assertEqual(self.client.get(ROOT).json()['integrations'][0]['config']['bookmark_ids'], [])

    def test_configuration_limits_tls_secret_retention_and_origin_change(self):
        self.setup_owner(); row = self.create()
        for change in ({'base_url': 'http://pve.test:8006'}, {'base_url': 'https://user:password@pve.test'}, {'base_url': 'https://pve.test/path'}, {'token': 'bad\r\nHeader'}, {'token_id': 'bad\r\nID'}, {'ca_certificate': 'invalid PEM'}, {'nodes': ['../escape']}, {'interval': 1}, {'user_id': 2}):
            response = self.client.post(ROOT, json=DATA | change, headers=HEADERS)
            self.assertEqual(response.status_code, 422, response.text)
        self.assertEqual(self.client.put(f'{ROOT}/{row["id"]}', json=DATA | {'token': None}, headers=HEADERS).status_code, 200)
        self.assertEqual(self.client.put(f'{ROOT}/{row["id"]}', json=DATA | {'token': None, 'base_url': 'https://other.test'}, headers=HEADERS).status_code, 422)
        for index in range(7): self.create(name=str(index))
        self.assertEqual(self.client.post(ROOT, json=DATA, headers=HEADERS).status_code, 409)

    def test_shared_cache_node_scope_error_preserves_last_good_data_and_stale_revision(self):
        self.setup_owner(); row = self.create(nodes=['pve1']); fake = FakePVE()
        with patch.object(Client, 'request', side_effect=fake.request):
            first = self.client.post(f'{ROOT}/{row["id"]}/refresh', headers=HEADERS).json()
            self.client.post(f'{ROOT}/{row["id"]}/refresh', headers=HEADERS)
        self.assertEqual(sum(path == '/cluster/resources' for _, path, _ in fake.calls), 1)
        self.assertEqual(first['data']['summary']['guests'], {'value': 1, 'total': 2})
        self.assertEqual(first['data']['summary']['cpu'], 25)
        self.assertNotIn('pve2', str(first['data']))
        self.assertNotIn('_permissions', str(first))
        with SessionLocal.begin() as db: db.get(ServiceIntegration, row['id']).next_check = 0
        with patch.object(Client, 'request', side_effect=ProxmoxError('연결 실패')):
            failed = self.client.post(f'{ROOT}/{row["id"]}/refresh', headers=HEADERS).json()
        self.assertEqual(failed['data']['summary'], first['data']['summary'])
        self.assertEqual(failed['data']['guests'][0]['actions'], [])
        self.assertEqual(failed['checked_at'], first['checked_at'])
        with SessionLocal.begin() as db: db.get(ServiceIntegration, row['id']).next_check = 0
        def revised(*args):
            with SessionLocal.begin() as db: db.get(ServiceIntegration, row['id']).revision = 'changed'
            return {'nodes': [], 'guests': [], 'storage': []}
        with patch('app.services.proxmox.inventory', side_effect=revised), patch('app.services.proxmox.permissions', return_value={}):
            proxmox.refresh(row['id'], 1)
        with SessionLocal() as db: self.assertEqual(db.get(ServiceIntegration, row['id']).error, '연결 실패')

    def test_permission_visibility_scope_and_revocation_at_execution(self):
        self.setup_owner(); row = self.create(); fake = FakePVE()
        with patch.object(Client, 'request', side_effect=fake.request):
            prepared = self.preview(row).json()
            fake.tree = {'/': {'VM.Audit': 1}}
            response = self.client.post(f'{ROOT}/{row["id"]}/execute', json={'intent': prepared['intent'], 'confirmation': '100'}, headers=HEADERS)
            self.assertEqual(response.status_code, 200, response.text)
            self.assertEqual(response.json()['state'], 'failed')
            self.assertFalse(any(method != 'GET' for method, _, _ in fake.calls))
            self.release_read(row['id'])
            result = self.client.get(f'{ROOT}/{row["id"]}/resource?resource=qemu/100').json()
            self.assertEqual(result['actions'], [])
        self.assertTrue(permitted({'/': {'VM.Audit': 1}}, '/vms/100', 'VM.Audit'))
        self.assertFalse(permitted({'/': {'VM.PowerMgmt': 1}, '/vms/100': {'VM.Audit': 0}}, '/vms/100', 'VM.PowerMgmt'))
        self.assertTrue(permitted({'/vms/100': {'VM.Audit': 0}}, '/vms/100', 'VM.Audit'))
        self.assertFalse(permitted({'/vms': {'VM.Audit': 0}}, '/vms/100', 'VM.Audit'))

    def test_confirmed_command_runs_once_and_tracks_real_upid(self):
        self.setup_owner(); row = self.create(); fake = FakePVE()
        with patch.object(Client, 'request', side_effect=fake.request):
            prepared = self.preview(row).json()
            base = f'{ROOT}/{row["id"]}'
            self.assertEqual(self.client.post(base + '/execute', json={'intent': prepared['intent'], 'confirmation': 'wrong'}, headers=HEADERS).status_code, 422)
            response = self.client.post(base + '/execute', json={'intent': prepared['intent'], 'confirmation': '100'}, headers=HEADERS)
            self.assertEqual(response.status_code, 200, response.text)
            task = response.json(); self.assertEqual(task['state'], 'running')
            self.assertEqual(self.client.post(base + '/execute', json={'intent': prepared['intent'], 'confirmation': '100'}, headers=HEADERS).status_code, 409)
            commands = [call for call in fake.calls if call[0] != 'GET']
            self.assertEqual(commands, [('POST', '/nodes/pve1/qemu/100/status/shutdown', {})])
            refreshed = self.client.post(base + '/tasks/' + task['id'] + '/refresh', headers=HEADERS)
            self.assertEqual(refreshed.json()['state'], 'ok')
            self.assertIn('/UPID%3Apve1%3A', fake.calls[-1][1])
        with SessionLocal() as db: self.assertIsNone(db.get(OperationPreview, prepared['intent']))

    def test_disabled_controls_unknown_endpoints_node_scope_and_stale_intents(self):
        self.setup_owner(); row = self.create(controls=False, nodes=['pve1']); fake = FakePVE()
        with patch.object(Client, 'request', side_effect=fake.request):
            self.assertEqual(self.preview(row).status_code, 403)
        self.assertEqual(self.client.put(f'{ROOT}/{row["id"]}', json=DATA | {'nodes':['pve1']}, headers=HEADERS).status_code, 200)
        with patch.object(Client, 'request', side_effect=fake.request):
            self.assertEqual(self.preview(row, resource='qemu/102').status_code, 404)
            prepared = self.preview(row).json()
            self.client.put(f'{ROOT}/{row["id"]}', json=DATA, headers=HEADERS)
            self.assertEqual(self.client.post(f'{ROOT}/{row["id"]}/execute', json={'intent': prepared['intent'], 'confirmation':'100'}, headers=HEADERS).status_code, 409)
        self.assertEqual(self.preview(row, action='arbitrary_api').status_code, 422)

    def test_no_automatic_replay_when_request_delivery_is_uncertain(self):
        self.setup_owner(); row = self.create(); fake = FakePVE()
        def transport(method, path, parameters=None):
            if method != 'GET': raise ProxmoxError('연결이 끊어졌습니다.')
            return fake.request(method, path, parameters)
        with patch.object(Client, 'request', side_effect=transport):
            prepared = self.preview(row).json()
            payload = {'intent': prepared['intent'], 'confirmation': '100'}
            response = self.client.post(f'{ROOT}/{row["id"]}/execute', json=payload, headers=HEADERS)
            self.assertEqual(response.json()['state'], 'unknown')
            self.assertEqual(self.client.post(f'{ROOT}/{row["id"]}/execute', json=payload, headers=HEADERS).status_code, 409)

    def test_changes_to_resource_identity_after_confirmation_never_send_command(self):
        self.setup_owner(); row = self.create(); fake = FakePVE()
        with patch.object(Client, 'request', side_effect=fake.request):
            prepared = self.preview(row).json()
            fake.resources[2]['name'] = 'replacement-vm'
            response = self.client.post(f'{ROOT}/{row["id"]}/execute', json={'intent':prepared['intent'],'confirmation':'100'}, headers=HEADERS)
            self.assertEqual(response.json()['state'],'failed')
            self.assertFalse(any(method != 'GET' for method, _, _ in fake.calls))


class OperationTests(unittest.TestCase):
    def setUp(self):
        self.fake = FakePVE()
        self.config = IntegrationData.model_validate(DATA).model_dump(mode='json', exclude={'token'})

    def plan(self, action, parameters=None, resource='qemu/100'):
        return plan(self.fake, self.config, ActionRequest(resource=resource, action=action, parameters=parameters or {}))

    def test_every_supported_operation_has_a_typed_bounded_route(self):
        examples = [('start',{},'status/start'),('shutdown',{},'status/shutdown'),('reboot',{},'status/reboot'),('stop',{},'status/stop'),('reset',{},'status/reset'),('suspend',{},'status/suspend'),('resume',{},'status/resume'),('snapshot',{'snapname':'before-update'},'snapshot'),('snapshot_delete',{'snapname':'before'},'snapshot/before'),('rollback',{'snapname':'before'},'snapshot/before/rollback'),('backup',{'storage':'local'},'vzdump'),('clone',{'storage':'local','newid':200,'name':'copy'},'clone'),('migrate',{'target':'pve2'},'migrate'),('cpu',{'value':4},'config'),('memory',{'value':4096},'config'),('onboot',{'value':1},'config'),('template',{},'template'),('delete',{},'qemu/100'),('node_reboot',{},'pve1/status'),('node_shutdown',{},'pve1/status')]
        for action, parameters, suffix in examples:
            with self.subTest(action=action):
                self.fake.resources[2]['status'] = 'stopped' if action in ('start','template','delete') else 'running'
                self.fake.current = {'status': self.fake.resources[2]['status'], 'qmpstatus': 'paused' if action == 'resume' else 'running'}
                result = self.plan(action, parameters, 'node/pve1' if action.startswith('node_') else 'qemu/100')
                self.assertTrue(result['path'].endswith('/'+suffix), result)
                self.assertNotIn('token', str(result))
        self.assertEqual(self.plan('memory',{'value':4096})['body'], {'memory':4096})
        self.assertEqual(self.plan('migrate',{'target':'pve2'})['body'], {'target':'pve2','online':1})

    def test_forbidden_extra_parameters_traversal_out_of_range_and_missing_target_privileges(self):
        for action, parameters in [('start',{'skiplock':1}),('snapshot',{'snapname':'../../escape'}),('snapshot_delete',{'snapname':'current'}),('cpu',{'value':True}),('cpu',{'value':129}),('memory',{'value':15}),('onboot',{'value':2}),('migrate',{'target':'pve1'}),('clone',{'storage':'local','newid':100,'name':'copy'}),('backup',{'storage':'other'})]:
            with self.subTest(action=action, parameters=parameters):
                with self.assertRaises(ProxmoxError): self.plan(action,parameters)
        self.fake.tree = {'/vms/100': {'VM.Audit':1,'VM.Clone':1}, '/storage/local':{'Datastore.AllocateSpace':1}}
        with self.assertRaises(ProxmoxError): self.plan('clone',{'storage':'local','newid':200,'name':'copy'})
        self.config['nodes'] = ['pve1']
        with self.assertRaises(ProxmoxError): self.plan('migrate',{'target':'pve2'})

    def test_lxc_never_receives_qemu_only_actions_and_locked_resources_are_rejected(self):
        data = proxmox.inventory(self.fake,self.config)
        self.assertNotIn('reset', capabilities(data['guests'][1],data,self.fake.tree))
        self.fake.current = {'status':'running'}
        result = self.plan('migrate',{'target':'pve2'},'lxc/101')
        self.assertEqual(result['body'],{'target':'pve2','restart':1})
        self.fake.current['lock'] = 'backup'
        with self.assertRaises(ProxmoxError): self.plan('shutdown')


class TransportTests(unittest.TestCase):
    def setUp(self):
        self.client = Client(IntegrationData.model_validate(DATA).model_dump(mode='json', exclude={'token'}), cipher().encrypt(b'fixture-only-token').decode())

    def test_pins_approved_address_verifies_tls_and_uses_only_token_header(self):
        connection = MagicMock()
        response = MagicMock(status=200)
        response.read1 = io.BytesIO(b'{"data":{"ok":true}}').read
        connection.getresponse.return_value = response
        context = MagicMock()
        with patch('app.services.proxmox.client.safe_addresses', return_value=['192.168.1.5']), patch('app.services.proxmox.client.socket.create_connection') as connect, patch('app.services.proxmox.client.secure_tls_context', return_value=context), patch('app.services.proxmox.client.pinned_http_connection', return_value=connection):
            self.assertEqual(self.client.request('POST','/nodes/pve1/qemu/100/snapshot',{'snapname':'before'}),{'ok':True})
        connect.assert_called_once_with(('192.168.1.5',8006),timeout=5)
        context.wrap_socket.assert_called_once_with(connect.return_value,server_hostname='pve.example.test')
        connection.putrequest.assert_called_once_with('POST','/api2/json/nodes/pve1/qemu/100/snapshot',skip_host=True,skip_accept_encoding=True)
        connection.putheader.assert_any_call('Authorization','PVEAPIToken=dock@pve!portal=fixture-only-token')
        self.assertFalse(any(call.args[0].lower() in ('cookie','csrfpreventiontoken') for call in connection.putheader.call_args_list))
        connection.endheaders.assert_called_once_with(b'snapname=before')
        connection.close.assert_called_once()

    def test_blocks_loopback_and_does_not_follow_redirect_or_leak_response(self):
        self.client.config['base_url'] = 'https://127.0.0.1:8006'
        with patch('app.services.proxmox.client.socket.create_connection') as connect:
            with self.assertRaises(ProxmoxError): self.client.request('GET','/cluster/resources')
            connect.assert_not_called()
        self.client.config['base_url'] = DATA['base_url']
        connection = MagicMock();connection.getresponse.return_value.status = 302
        with patch('app.services.proxmox.client.safe_addresses',return_value=['192.168.1.5']), patch('app.services.proxmox.client.socket.create_connection'), patch('app.services.proxmox.client.secure_tls_context'), patch('app.services.proxmox.client.pinned_http_connection',return_value=connection):
            with self.assertRaises(ProxmoxError) as failure: self.client.request('GET','/cluster/resources')
        self.assertNotIn('fixture-only-token',str(failure.exception))
        self.assertEqual(connection.putrequest.call_count,1)
        connection.getresponse.return_value.read1.assert_not_called()

    def test_response_size_and_authentication_failures_are_bounded_and_redacted(self):
        for status in (200,403,500):
            connection = MagicMock();response = MagicMock(status=status)
            response.read1 = io.BytesIO(b'x'*(2*1024*1024+1)).read
            connection.getresponse.return_value = response
            with patch('app.services.proxmox.client.safe_addresses',return_value=['192.168.1.5']), patch('app.services.proxmox.client.socket.create_connection'), patch('app.services.proxmox.client.secure_tls_context'), patch('app.services.proxmox.client.pinned_http_connection',return_value=connection):
                with self.assertRaises(ProxmoxError) as caught: self.client.request('GET','/cluster/resources')
            self.assertNotIn('fixture-only-token',caught.exception.public_message)
            if status == 403: self.assertEqual(caught.exception.status,403)
            if status == 200: self.assertIn('2MB',caught.exception.public_message)
