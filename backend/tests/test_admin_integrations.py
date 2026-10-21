import json
import time
import unittest
from unittest.mock import patch

import httpx
from fastapi import HTTPException
from fastapi.testclient import TestClient
from sqlalchemy import func, select

import test_auth as legacy_tests
from test_auth import HEADERS
from app.core.security import cipher
from app.db.models import Bookmark, Category, OIDCIdentity, ProxyPreview, ProxySource, Setting, User
from app.db.session import SessionLocal
from app.main import app
from app.schemas.proxy import PreviewData
from app.services.proxy import fetch_hosts, normalize_hosts


class AdminIntegrationTests(unittest.TestCase):
    setUp = legacy_tests.AuthenticationTests.setUp
    tearDown = legacy_tests.AuthenticationTests.tearDown
    setup_owner = legacy_tests.AuthenticationTests.setup_owner

    def config(self, **overrides):
        return {'enabled': True, 'label': '회사 계정', 'issuer': 'https://id.example.test/realms/dock',
                'client_id': 'portal', 'client_secret': 'private-client-secret',
                'redirect_uri': 'https://dock.example.test/api/auth/oidc/callback', **overrides}

    def source(self):
        response = self.client.post('/api/admin/proxy-sources', json={'name': 'Home', 'provider': 'npm', 'base_url': 'http://192.168.1.2:81', 'token': 'private-api-token'}, headers=HEADERS)
        self.assertEqual(response.status_code, 200, response.text)
        return response.json()

    def preview(self, source):
        with patch('app.api.proxy.fetch_hosts', return_value=[{'domain_names': ['app.example.test', 'other.example.test'], 'enabled': True, 'certificate_id': 1}]):
            response = self.client.post('/api/admin/proxy-sources/'+source['id']+'/preview', json={}, headers=HEADERS)
        self.assertEqual(response.status_code, 200, response.text)
        return response.json()

    def test_oidc_settings_encrypted_and_secret_preserved_without_env_override(self):
        self.setup_owner()
        response = self.client.put('/api/admin/sso', json=self.config(), headers=HEADERS)
        self.assertEqual(response.status_code, 200, response.text)
        self.assertTrue(response.json()['has_secret'])
        self.assertNotIn('private-client-secret', response.text)
        self.assertNotIn('secret_encrypted', response.text)
        with SessionLocal() as db:
            stored = db.get(Setting, 'oidc').value
            self.assertNotIn('private-client-secret', json.dumps(stored))
            self.assertEqual(cipher().decrypt(stored['secret_encrypted'].encode()).decode(), 'private-client-secret')
        response = self.client.put('/api/admin/sso', json=self.config(label='변경', client_secret=None), headers=HEADERS)
        self.assertTrue(response.json()['has_secret'])
        self.assertEqual(self.client.get('/api/auth/status').json()['sso_label'], '변경')
        with patch.dict('os.environ', {'OIDC_LABEL': 'ignored', 'OIDC_ISSUER_URL': 'https://ignored.test'}):
            self.assertEqual(self.client.get('/api/admin/sso').json()['issuer'], self.config()['issuer'])

    def test_oidc_requires_complete_configuration_and_valid_urls(self):
        self.setup_owner()
        self.assertEqual(self.client.put('/api/admin/sso', json=self.config(client_secret=None), headers=HEADERS).status_code, 422)
        for change in ({'issuer': 'file:///etc/passwd'}, {'issuer': 'https://name:secret@id.test'}, {'redirect_uri': 'https://dock.test/other'}, {'label': '  '}, {'issuer': ''}):
            self.assertEqual(self.client.put('/api/admin/sso', json=self.config(**change), headers=HEADERS).status_code, 422, change)

    def test_create_oidc_account_requires_provider_unique_subject_and_no_password(self):
        self.setup_owner()
        data = {'username': 'sso-person', 'login_type': 'oidc', 'oidc_subject': 'external-123'}
        self.assertEqual(self.client.post('/api/admin/users', json=data, headers=HEADERS).status_code, 409)
        self.client.put('/api/admin/sso', json=self.config(), headers=HEADERS)
        response = self.client.post('/api/admin/users', json=data, headers=HEADERS)
        self.assertEqual(response.status_code, 200, response.text)
        self.assertFalse(response.json()['has_password'])
        with SessionLocal() as db:
            identity = db.scalar(select(OIDCIdentity))
            self.assertEqual(identity.issuer, self.config()['issuer'])
            self.assertEqual(identity.subject, 'external-123')
        self.assertEqual(self.client.post('/api/admin/users', json={**data, 'username': 'duplicate'}, headers=HEADERS).status_code, 409)
        for change in ({'password': 'a-long-password'}, {'oidc_subject': ''}, {'oidc_subject': '   '}):
            self.assertEqual(self.client.post('/api/admin/users', json={**data, **change}, headers=HEADERS).status_code, 422)
        self.assertEqual(self.client.post('/api/admin/users', json={'username': 'no-password'}, headers=HEADERS).status_code, 422)

    def test_sso_only_admin_cannot_disable_only_login_route(self):
        self.setup_owner()
        self.client.put('/api/admin/sso', json=self.config(), headers=HEADERS)
        with SessionLocal.begin() as db:
            db.get(User, 1).password_hash = None
        self.assertEqual(self.client.put('/api/admin/sso', json=self.config(enabled=False), headers=HEADERS).status_code, 409)
        self.assertEqual(self.client.put('/api/admin/sso', json=self.config(issuer='https://other.test'), headers=HEADERS).status_code, 409)

    def test_proxy_source_secret_encryption_preserve_and_replacement(self):
        self.setup_owner()
        source = self.source()
        self.assertTrue(source['has_token'])
        self.assertNotIn('private-api-token', json.dumps(source))
        with SessionLocal() as db:
            stored = db.get(ProxySource, source['id']).token_encrypted
            self.assertNotIn('private-api-token', stored)
            self.assertEqual(cipher().decrypt(stored.encode()).decode(), 'private-api-token')
        payload = {key: source[key] for key in ('name', 'provider', 'base_url', 'verify_tls')}
        endpoint = '/api/admin/proxy-sources/'+source['id']
        self.assertEqual(self.client.put(endpoint, json=payload, headers=HEADERS).status_code, 200)
        self.assertEqual(self.client.put(endpoint, json={**payload, 'base_url': 'https://new.test'}, headers=HEADERS).status_code, 422)
        self.assertEqual(self.client.put(endpoint, json={**payload, 'base_url': 'https://new.test', 'token': 'new-token'}, headers=HEADERS).status_code, 200)

    def test_import_only_selected_entries_duplicate_and_replay_protection(self):
        self.setup_owner()
        source = self.source()
        preview = self.preview(source)
        category = self.client.get('/api/portal').json()['tabs'][0]['categories'][0]['id']
        payload = {'preview_id': preview['preview_id'], 'category_id': category, 'entry_ids': ['0']}
        endpoint = '/api/admin/proxy-sources/'+source['id']+'/import'
        self.assertEqual(self.client.post(endpoint, json={**payload, 'entry_ids': ['unknown']}, headers=HEADERS).status_code, 422)
        self.assertEqual(self.client.post(endpoint, json=payload, headers=HEADERS).json(), {'added': 1, 'duplicates': 0})
        self.assertEqual(self.client.post(endpoint, json=payload, headers=HEADERS).status_code, 409)
        preview = self.preview(source)
        self.assertTrue(preview['entries'][0]['existing'])
        response = self.client.post(endpoint, json={**payload, 'preview_id': preview['preview_id'], 'entry_ids': ['0', '1']}, headers=HEADERS)
        self.assertEqual(response.json(), {'added': 1, 'duplicates': 1})

    def test_expired_preview_and_changed_source_are_rejected(self):
        self.setup_owner()
        source = self.source()
        category = self.client.get('/api/portal').json()['tabs'][0]['categories'][0]['id']
        for change in ('expire', 'revision'):
            preview = self.preview(source)
            with SessionLocal.begin() as db:
                if change == 'expire':
                    db.get(ProxyPreview, preview['preview_id']).expires_at = time.time()-1
                else:
                    db.get(ProxySource, source['id']).revision = 'changed'
            response = self.client.post('/api/admin/proxy-sources/'+source['id']+'/import', json={'preview_id': preview['preview_id'], 'category_id': category, 'entry_ids': ['0']}, headers=HEADERS)
            self.assertEqual(response.status_code, 409)

    def test_existing_manual_bookmark_canonical_url_is_not_duplicated(self):
        self.setup_owner()
        source = self.source()
        category = self.client.get('/api/portal').json()['tabs'][0]['categories'][0]['id']
        self.assertEqual(self.client.post('/api/bookmarks', json={'category_id': category, 'name': 'Manual', 'url': 'https://APP.example.test:443'}, headers=HEADERS).status_code, 200)
        preview = self.preview(source)
        self.assertTrue(preview['entries'][0]['existing'])

    def test_import_ownership_and_admin_authorization(self):
        self.setup_owner()
        source = self.source()
        preview = self.preview(source)
        member = self.client.post('/api/admin/users', json={'username': 'member', 'password': 'a-member-password'}, headers=HEADERS).json()
        with SessionLocal() as db:
            category = db.scalar(select(Category).where(Category.user_id == member['id'])).id
        endpoint = '/api/admin/proxy-sources/'+source['id']
        payload = {'preview_id': preview['preview_id'], 'category_id': category, 'entry_ids': ['0']}
        self.assertEqual(self.client.post(endpoint+'/import', json=payload, headers=HEADERS).status_code, 404)
        other = TestClient(app)
        other.post('/api/auth/login', json={'username': 'member', 'password': 'a-member-password'}, headers=HEADERS)
        for method, path, data in [('GET', '/api/admin/proxy-sources', None), ('POST', endpoint+'/preview', {}), ('POST', endpoint+'/import', payload), ('DELETE', endpoint, None), ('PUT', '/api/admin/sso', self.config())]:
            self.assertEqual(other.request(method, path, json=data, headers=HEADERS).status_code, 403)
        self.assertEqual(other.get('/api/portal').status_code, 200)
        self.assertEqual(self.client.post(endpoint+'/preview', json={}).status_code, 403)

    def test_source_delete_cleans_preview_and_keeps_bookmarks(self):
        self.setup_owner()
        source = self.source()
        self.preview(source)
        with SessionLocal() as db:
            count = db.scalar(select(func.count()).select_from(Bookmark))
        self.assertEqual(self.client.delete('/api/admin/proxy-sources/'+source['id'], headers=HEADERS).status_code, 200)
        with SessionLocal() as db:
            self.assertEqual(db.scalar(select(func.count()).select_from(ProxyPreview)), 0)
            self.assertEqual(db.scalar(select(func.count()).select_from(Bookmark)), count)


class ProxyAdapterTests(unittest.TestCase):
    def test_npm_domains_public_scheme_and_disabled_filtering(self):
        entries, skipped = normalize_hosts('npm', [
            {'domain_names': ['app.test', 'alias.test', '*.test', 'app.test', 'bad/path'], 'certificate_id': 1},
            {'domain_names': ['off.test'], 'enabled': False},
            {'domain_names': ['plain.test'], 'forward_scheme': 'https', 'certificate_id': 0},
        ], PreviewData())
        self.assertEqual([item['url'] for item in entries], ['https://app.test', 'https://alias.test', 'http://plain.test'])
        self.assertEqual(skipped, 4)

    def test_npg_and_zoraxy_fields_and_protocol_override(self):
        entries, _ = normalize_hosts('npg', [{'domain_names': ['safe.test'], 'ssl_enabled': True}, {'domain_names': ['stream.test'], 'proxy_type': 'stream'}], PreviewData(public_port=8443))
        self.assertEqual(entries[0]['url'], 'https://safe.test:8443')
        entries, _ = normalize_hosts('zoraxy', [
            {'RootOrMatchingDomain': 'z.test', 'MatchingDomainAlias': ['alias.test'], 'ProxyType': 1},
            {'RootOrMatchingDomain': 'off.test', 'Disabled': True},
            {'RootOrMatchingDomain': 'plain.test', 'BypassGlobalTLS': True},
        ], PreviewData(scheme='https'))
        self.assertEqual([row['url'] for row in entries], ['https://z.test', 'https://alias.test', 'http://plain.test'])
        with self.assertRaises(HTTPException):
            normalize_hosts('zoraxy', [], PreviewData())

    def fetch(self, provider, handler):
        original_client = httpx.Client
        source = ProxySource(provider=provider, base_url='https://proxy.test/prefix', token_encrypted=cipher().encrypt(b'secret-token').decode(), verify_tls=True)
        with patch('app.services.proxy.httpx.Client', side_effect=lambda **kwargs: original_client(transport=httpx.MockTransport(handler), **kwargs)):
            return fetch_hosts(source)

    def test_adapter_paths_bearer_and_pagination(self):
        paths = {'npm': '/prefix/api/nginx/proxy-hosts', 'zoraxy': '/prefix/plugin/api/proxy/list', 'npg': '/prefix/api/v1/proxy-hosts'}
        for provider, path in paths.items():
            calls = []
            def handler(request):
                self.assertEqual(request.method, 'GET')
                self.assertEqual(request.url.path, path)
                self.assertEqual(request.headers['Authorization'], 'Bearer secret-token')
                calls.append(request)
                if provider == 'npg':
                    self.assertEqual(request.url.params['per_page'], '100')
                    return httpx.Response(200, json={'data': [{'domain_names': ['page'+request.url.params['page']+'.test']}], 'total_pages': 2})
                if provider == 'zoraxy':
                    self.assertEqual(request.url.params['type'], 'host')
                return httpx.Response(200, json=[])
            result = self.fetch(provider, handler)
            self.assertEqual(len(calls), 2 if provider == 'npg' else 1)
            self.assertEqual(len(result), 2 if provider == 'npg' else 0)

    def test_errors_redirects_and_invalid_payloads_do_not_expose_upstream_body(self):
        for status in (302, 401, 403, 404, 500):
            with self.assertRaises(HTTPException) as caught:
                self.fetch('npm', lambda request: httpx.Response(status, text='private details secret-token', headers={'Location': 'https://other.test'}))
            self.assertNotIn('secret-token', caught.exception.detail)
        for payload in ({'error': 'login_required'}, 'html'):
            with self.assertRaises(HTTPException):
                self.fetch('npm', lambda request: httpx.Response(200, json=payload))
        with self.assertRaises(HTTPException):
            self.fetch('npg', lambda request: httpx.Response(200, json={'data': [], 'total_pages': 11}))
        with self.assertRaises(HTTPException):
            self.fetch('npm', lambda request: httpx.Response(200, content=b'x'*(2*1024*1024+1)))
