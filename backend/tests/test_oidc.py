import os
import time
import unittest
from urllib.parse import parse_qs, urlencode, urlsplit
from unittest.mock import patch

import pyotp
from fastapi.testclient import TestClient
from sqlalchemy import func, select

import test_auth as legacy_tests
from test_auth import CREDENTIALS, HEADERS
from app.db.session import SessionLocal
from app.main import app
from app.db.models import OAuthState, OIDCIdentity, User
from app.core.security import cipher
from oidc_provider import Provider


class OIDCTests(unittest.TestCase):
    setUpBase = legacy_tests.AuthenticationTests.setUp
    tearDownBase = legacy_tests.AuthenticationTests.tearDown
    setup_owner = legacy_tests.AuthenticationTests.setup_owner

    @classmethod
    def setUpClass(cls):
        cls.provider = Provider()

    @classmethod
    def tearDownClass(cls):
        cls.provider.close()

    def setUp(self):
        self.environment = patch.dict(os.environ, {'OIDC_ISSUER_URL':self.provider.issuer,'OIDC_CLIENT_ID':'test-client',
            'OIDC_CLIENT_SECRET':'test-secret','OIDC_REDIRECT_URI':'http://testserver/api/auth/oidc/callback','OIDC_ALLOW_SIGNUP':'true'})
        self.environment.start()
        self.provider.claim_overrides = {}
        self.provider.bad_signature = False
        self.provider.pkce_verified = False
        self.setUpBase()
        self.setup_owner()
        response = self.client.post('/api/admin/users', json={'username': 'oidc-member', 'login_type': 'oidc', 'oidc_subject': self.provider.subject}, headers=HEADERS)
        self.assertEqual(response.status_code, 200, response.text)
        self.client.post('/api/auth/logout',headers=HEADERS)

    def tearDown(self):
        self.tearDownBase()
        self.environment.stop()

    def start(self):
        response=self.client.get('/api/auth/oidc/login',follow_redirects=False)
        self.assertEqual(response.status_code,302,response.text)
        query=parse_qs(urlsplit(response.headers['location']).query)
        self.assertEqual(query['code_challenge_method'],['S256'])
        self.assertIn('nonce',query)
        return query

    def finish(self,query,client=None):
        code=self.provider.issue_code(query)
        return (client or self.client).get('/api/auth/oidc/callback?'+urlencode({'code':code,'state':query['state'][0]}),follow_redirects=False)

    def test_real_oidc_pkce_signed_identity_and_repeated_login(self):
        response=self.finish(self.start())
        self.assertEqual(response.headers['location'],'http://testserver/')
        self.assertTrue(self.provider.pkce_verified)
        devices = self.client.get('/api/account/sessions')
        self.assertEqual(devices.status_code, 200, devices.text)
        self.assertTrue(devices.json()['current_session']['id'])
        status=self.client.get('/api/auth/status').json()
        self.assertTrue(status['authenticated'])
        self.assertEqual(status['role'],'member')
        self.assertNotEqual(status['username'],CREDENTIALS['username'])
        with SessionLocal() as db:
            self.assertEqual(db.scalar(select(func.count()).select_from(User)),2)
        self.client.post('/api/auth/logout',headers=HEADERS)
        self.finish(self.start())
        with SessionLocal() as db:
            self.assertEqual(db.scalar(select(func.count()).select_from(User)),2)

    def test_state_is_browser_bound_and_single_use(self):
        query=self.start()
        other=TestClient(app)
        response=self.finish(query,other)
        self.assertIn('sso_error=1',response.headers['location'])
        self.assertFalse(other.get('/api/auth/status').json()['authenticated'])
        query=self.start()
        self.assertNotIn('sso_error',self.finish(query).headers['location'])
        self.client.post('/api/auth/logout',headers=HEADERS)
        self.assertIn('sso_error',self.finish(query).headers['location'])

    def test_claims_and_signature_are_validated(self):
        for override in ({'nonce':'wrong'},{'aud':'another-client'},{'iss':'https://another-issuer.test'},{'exp':int(time.time())-600}):
            self.provider.claim_overrides=override
            response=self.finish(self.start())
            self.assertIn('sso_error',response.headers['location'],override)
            self.assertFalse(self.client.get('/api/auth/status').json()['authenticated'])
        self.provider.claim_overrides={}
        self.provider.bad_signature=True
        self.assertIn('sso_error',self.finish(self.start()).headers['location'])

    def test_signup_is_disabled_by_default_and_explicit_link_preserves_role(self):
        self.provider.claim_overrides = {'sub': 'unregistered-user'}
        self.assertIn('sso_error',self.finish(self.start()).headers['location'])
        self.provider.claim_overrides = {}
        with SessionLocal.begin() as db:
            db.scalar(select(OIDCIdentity)).user_id = 1
        self.assertEqual(self.finish(self.start()).headers['location'],'http://testserver/')
        self.assertEqual(self.client.get('/api/auth/status').json()['role'],'admin')

    def test_local_second_factor_is_required_for_linked_oidc_user(self):
        secret=pyotp.random_base32()
        with SessionLocal.begin() as db:
            user=db.get(User,1)
            user.totp_secret=cipher().encrypt(secret.encode()).decode()
            db.scalar(select(OIDCIdentity)).user_id = 1
        self.finish(self.start())
        status=self.client.get('/api/auth/status').json()
        self.assertFalse(status['authenticated'])
        self.assertTrue(status['mfa_required'])
        self.assertEqual(self.client.get('/api/portal').status_code,401)
        response=self.client.post('/api/auth/mfa',json={'code':pyotp.TOTP(secret).now()},headers=HEADERS)
        self.assertEqual(response.status_code,200,response.text)

    def test_disabled_account_and_expired_state_cannot_login(self):
        query=self.start()
        with SessionLocal.begin() as db:
            db.scalar(select(OAuthState)).expires_at=time.time()-1
        self.assertIn('sso_error',self.finish(query).headers['location'])
        with SessionLocal.begin() as db:
            db.get(User,2).active=False
        self.assertIn('sso_error',self.finish(self.start()).headers['location'])

    def test_configuration_change_invalidates_inflight_authentication(self):
        query = self.start()
        with SessionLocal.begin() as db:
            from app.db.models import Setting
            row = db.get(Setting, 'oidc')
            row.value = {**row.value, 'revision': 'changed'}
        self.assertIn('sso_error', self.finish(query).headers['location'])

    def test_sso_only_allows_signed_oidc_login_and_keeps_local_second_factor(self):
        admin = TestClient(app)
        self.assertEqual(admin.post('/api/auth/login', json=CREDENTIALS, headers=HEADERS).status_code, 200)
        self.assertEqual(admin.post('/api/admin/users/1/identities', json={
            'issuer': self.provider.issuer, 'subject': 'another-admin-subject'}, headers=HEADERS).status_code, 200)
        secret = pyotp.random_base32()
        with SessionLocal.begin() as db:
            db.get(User, 2).totp_secret = cipher().encrypt(secret.encode()).decode()
        response = admin.put('/api/admin/sso', json={
            'enabled': True, 'login_mode': 'sso_only', 'issuer': self.provider.issuer,
            'client_id': 'test-client', 'redirect_uri': 'http://testserver/api/auth/oidc/callback'}, headers=HEADERS)
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(self.client.post('/api/auth/login', json=CREDENTIALS, headers=HEADERS).status_code, 409)
        response = self.finish(self.start())
        self.assertEqual(response.headers['location'], 'http://testserver/')
        status = self.client.get('/api/auth/status').json()
        self.assertFalse(status['password_login_enabled'])
        self.assertTrue(status['mfa_required'])
        self.assertFalse(status['authenticated'])
        response = self.client.post('/api/auth/mfa', json={'code': pyotp.TOTP(secret).now()}, headers=HEADERS)
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(self.client.get('/api/auth/status').json()['role'], 'member')
        self.assertTrue(self.provider.pkce_verified)
