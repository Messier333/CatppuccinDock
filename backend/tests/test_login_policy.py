import contextlib
import io
import time
import unittest
from unittest.mock import patch

from fastapi.testclient import TestClient
from sqlalchemy import select, text

import test_auth as legacy_tests
from test_auth import CREDENTIALS, HEADERS
from app.cli import main as recovery_command
from app.core.security import cipher, token_hash
from app.db.migrations import migrate
from app.db.models import MFAChallenge, OIDCIdentity, Setting, User
from app.db.session import SessionLocal, engine
from app.main import app
from app.services.auth import MFA_COOKIE


class LoginPolicyTests(unittest.TestCase):
    setUp = legacy_tests.AuthenticationTests.setUp
    tearDown = legacy_tests.AuthenticationTests.tearDown
    setup_owner = legacy_tests.AuthenticationTests.setup_owner

    def config(self, **overrides):
        return {'enabled': True, 'login_mode': 'both', 'label': '회사 계정',
                'issuer': 'https://id.example.test', 'client_id': 'portal',
                'client_secret': 'private-policy-secret',
                'redirect_uri': 'https://dock.example.test/api/auth/oidc/callback', **overrides}

    def save(self, **overrides):
        return self.client.put('/api/admin/sso', json=self.config(**overrides), headers=HEADERS)

    def link_admin(self, issuer=None):
        response = self.client.post('/api/admin/users/1/identities', json={
            'issuer': issuer or self.config()['issuer'], 'subject': 'external-admin'}, headers=HEADERS)
        self.assertEqual(response.status_code, 200, response.text)
        return response.json()['id']

    def enable_only(self):
        self.link_admin()
        response = self.save(login_mode='sso_only')
        self.assertEqual(response.status_code, 200, response.text)
        return response

    def test_existing_settings_default_to_password_login_without_changing_secret(self):
        self.setup_owner()
        self.assertEqual(self.save().status_code, 200)
        with SessionLocal.begin() as db:
            row = db.get(Setting, 'oidc')
            row.value = {key: value for key, value in row.value.items() if key != 'login_mode'}
        public = self.client.get('/api/auth/status').json()
        self.assertTrue(public['password_login_enabled'])
        self.assertTrue(public['sso_enabled'])
        self.assertNotIn('private-policy-secret', str(public))
        self.assertEqual(self.client.get('/api/admin/sso').json()['login_mode'], 'both')
        self.assertEqual(self.save(client_secret=None).status_code, 200)
        with SessionLocal() as db:
            self.assertEqual(cipher().decrypt(db.get(Setting, 'oidc').value['secret_encrypted'].encode()).decode(), 'private-policy-secret')

    def test_sso_only_requires_enabled_complete_provider_and_matching_active_admin(self):
        self.setup_owner()
        for change in ({'enabled': False}, {'client_secret': None}, {'issuer': ''}):
            self.assertEqual(self.save(login_mode='sso_only', **change).status_code, 422, change)
        self.assertEqual(self.save(login_mode='sso_only').status_code, 409)
        self.link_admin('https://another-issuer.example.test')
        self.assertEqual(self.save(login_mode='sso_only').status_code, 409)
        self.assertEqual(self.save().status_code, 200)
        member = self.client.post('/api/admin/users', json={
            'username': 'oidc-member', 'login_type': 'oidc', 'oidc_subject': 'member-sub'}, headers=HEADERS)
        self.assertEqual(member.status_code, 200)
        self.assertEqual(self.save(login_mode='sso_only').status_code, 409)
        self.link_admin()
        self.assertEqual(self.save(login_mode='sso_only').status_code, 200)

    def test_policy_is_server_enforced_for_admin_and_member_and_preserves_current_session(self):
        self.setup_owner()
        self.client.post('/api/admin/users', json={'username': 'member', 'password': 'a-member-password'}, headers=HEADERS)
        self.enable_only()
        other = TestClient(app)
        state = other.get('/api/auth/status').json()
        self.assertFalse(state['password_login_enabled'])
        self.assertTrue(state['sso_enabled'])
        self.assertNotIn('issuer', state)
        for credentials in (CREDENTIALS, {**CREDENTIALS, 'password': 'wrong'}, {'username': 'member', 'password': 'a-member-password'}):
            response = other.post('/api/auth/login', json=credentials, headers=HEADERS)
            self.assertEqual(response.status_code, 409, response.text)
            self.assertFalse(other.get('/api/auth/status').json()['authenticated'])
        self.assertEqual(other.post('/api/auth/setup', json={**CREDENTIALS, 'setup_code': 'test-first-run-code'}, headers=HEADERS).status_code, 409)
        self.assertEqual(self.client.get('/api/admin/sso').status_code, 200)
        self.assertEqual(self.save(enabled=False, client_secret=None).status_code, 200)
        state = other.get('/api/auth/status').json()
        self.assertTrue(state['password_login_enabled'])
        self.assertFalse(state['sso_enabled'])
        self.assertEqual(other.post('/api/auth/login', json=CREDENTIALS, headers=HEADERS).status_code, 200)

    def test_switch_discards_password_mfa_and_rejects_late_challenge(self):
        self.setup_owner()
        secret = 'JBSWY3DPEHPK3PXP'
        with SessionLocal.begin() as db:
            db.get(User, 1).totp_secret = cipher().encrypt(secret.encode()).decode()
        other = TestClient(app)
        response = other.post('/api/auth/login', json=CREDENTIALS, headers=HEADERS)
        self.assertTrue(response.json()['mfa_required'])
        self.enable_only()
        self.assertFalse(other.get('/api/auth/status').json()['mfa_required'])
        with SessionLocal() as db:
            self.assertIsNone(db.scalar(select(MFAChallenge)))
        with SessionLocal.begin() as db:
            db.add(MFAChallenge(token_hash=token_hash('late-local-challenge'), user_id=1, expires_at=time.time()+300, auth_method='local'))
        other.cookies.set(MFA_COOKIE, 'late-local-challenge')
        self.assertFalse(other.get('/api/auth/status').json()['mfa_required'])
        self.assertEqual(other.post('/api/auth/mfa', json={'code': '123456'}, headers=HEADERS).status_code, 401)
        self.assertFalse(other.get('/api/auth/status').json()['authenticated'])

    def test_last_sso_admin_cannot_be_unlinked_demoted_disabled_or_switched_to_other_issuer(self):
        self.setup_owner()
        local_admin = self.client.post('/api/admin/users', json={
            'username': 'local-admin', 'password': 'another-admin-password', 'role': 'admin'}, headers=HEADERS)
        self.assertEqual(local_admin.status_code, 200)
        identity = self.link_admin()
        self.assertEqual(self.save(login_mode='sso_only').status_code, 200)
        self.assertEqual(self.client.delete(f'/api/admin/users/1/identities/{identity}', headers=HEADERS).status_code, 409)
        for change in ({'role': 'member'}, {'role': 'admin', 'active': False}):
            self.assertEqual(self.client.put('/api/admin/users/1', json={'username': CREDENTIALS['username'], **change}, headers=HEADERS).status_code, 409)
        self.assertEqual(self.save(login_mode='sso_only', issuer='https://other.example.test').status_code, 409)
        self.assertEqual(self.client.get('/api/admin/users').status_code, 200)
        with SessionLocal() as db:
            self.assertTrue(db.get(User, 1).active)
            self.assertEqual(db.get(User, 1).role, 'admin')
            self.assertIsNotNone(db.get(OIDCIdentity, identity))
        self.assertEqual(self.save().status_code, 200)
        self.assertEqual(self.client.delete(f'/api/admin/users/1/identities/{identity}', headers=HEADERS).status_code, 200)

    def test_non_admin_cannot_change_login_policy(self):
        self.setup_owner()
        self.client.post('/api/admin/users', json={'username': 'member', 'password': 'a-member-password'}, headers=HEADERS)
        member = TestClient(app)
        member.post('/api/auth/login', json={'username': 'member', 'password': 'a-member-password'}, headers=HEADERS)
        self.assertEqual(member.put('/api/admin/sso', json=self.config(login_mode='sso_only'), headers=HEADERS).status_code, 403)
        self.assertEqual(self.client.put('/api/admin/sso', json=self.config()).status_code, 403)

    def test_server_recovery_reenables_password_without_disabling_or_leaking_sso(self):
        self.setup_owner()
        self.enable_only()
        with SessionLocal() as db:
            original = dict(db.get(Setting, 'oidc').value)
        output = io.StringIO()
        with patch('sys.argv', ['app.cli', 'enable-password-login']), contextlib.redirect_stdout(output):
            recovery_command()
        self.assertNotIn('private-policy-secret', output.getvalue())
        with SessionLocal() as db:
            config = db.get(Setting, 'oidc').value
            self.assertEqual(config['secret_encrypted'], original['secret_encrypted'])
            self.assertTrue(config['enabled'])
            self.assertEqual(config['login_mode'], 'both')
            self.assertNotEqual(config['revision'], original['revision'])
        other = TestClient(app)
        self.assertEqual(other.post('/api/auth/login', json=CREDENTIALS, headers=HEADERS).status_code, 200)

    def test_upgrade_preserves_existing_password_challenge_and_defaults_its_method(self):
        self.setup_owner()
        with engine.begin() as connection:
            connection.execute(text('DROP TABLE dock_mfa_challenges'))
            connection.execute(text('CREATE TABLE dock_mfa_challenges (token_hash VARCHAR(64) PRIMARY KEY, user_id INTEGER NOT NULL, expires_at FLOAT NOT NULL, attempts INTEGER NOT NULL)'))
            connection.execute(text('INSERT INTO dock_mfa_challenges (token_hash,user_id,expires_at,attempts) VALUES (:token,1,:expiry,0)'), {'token': token_hash('old-challenge'), 'expiry': time.time()+300})
        migrate()
        migrate()
        with SessionLocal() as db:
            challenge = db.get(MFAChallenge, token_hash('old-challenge'))
            self.assertEqual(challenge.auth_method, 'local')
            self.assertEqual(db.get(User, 1).username, CREDENTIALS['username'])
