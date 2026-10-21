import time
import unittest
from unittest.mock import patch
from uuid import UUID, uuid4

import pyotp
from fastapi.testclient import TestClient
from sqlalchemy import select, text

import test_auth as legacy
from test_auth import CREDENTIALS, HEADERS
from app.core.security import cipher, token_hash
from app.db.migrations import migrate
from app.db.models import LoginSession, MFAChallenge, User
from app.db.session import SessionLocal, engine
from app.main import app
from app.services.auth import COOKIE_NAME, MFA_COOKIE
from app.services.login_devices import device_details

CHROME = 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/131.0.0.0 Safari/537.36'
IPHONE = 'Mozilla/5.0 (iPhone; CPU iPhone OS 18_0 like Mac OS X) AppleWebKit/605.1.15 Version/18.0 Mobile/15E148 Safari/604.1'


class LoginDevicesTests(unittest.TestCase):
    setUp = legacy.AuthenticationTests.setUp
    tearDown = legacy.AuthenticationTests.tearDown
    setup_owner = legacy.AuthenticationTests.setup_owner

    def login(self, credentials=CREDENTIALS, agent=IPHONE):
        client = TestClient(app, headers={'User-Agent': agent, 'X-Real-IP': '2001:db8::2'})
        result = client.post('/api/auth/login', json=credentials, headers=HEADERS)
        self.assertEqual(result.status_code, 200, result.text)
        return client

    def listing(self, client=None):
        response = (client or self.client).get('/api/account/sessions')
        self.assertEqual(response.status_code, 200, response.text)
        return response.json()

    def member(self):
        credentials = {'username': 'devices-member', 'password': 'a-member-password'}
        result = self.client.post('/api/admin/users', json=credentials, headers=HEADERS)
        self.assertEqual(result.status_code, 200, result.text)
        return self.login(credentials)

    def test_current_device_metadata_and_public_identifier_never_expose_credentials(self):
        self.client.headers.update({'User-Agent': CHROME, 'X-Real-IP': '192.0.2.10'})
        self.setup_owner()
        result = self.listing()
        current = result['current_session']
        self.assertEqual((current['label'], current['kind'], current['ip_address']), ('Chrome · Windows', 'desktop', '192.0.2.10'))
        UUID(current['id'])
        token = self.client.cookies.get(COOKIE_NAME)
        self.assertNotIn(token, str(result))
        self.assertNotIn(token_hash(token), str(result))
        self.assertNotIn('user_agent', current)
        self.assertEqual(result['items'], [])
        self.assertEqual(result['total_others'], 0)

    def test_revoke_one_device_blocks_replayed_cookie_and_preserves_current_and_other_user(self):
        self.setup_owner()
        other = self.login()
        member = self.member()
        token = other.cookies.get(COOKIE_NAME)
        session_id = self.listing(other)['current_session']['id']
        response = self.client.delete('/api/account/sessions/'+session_id, headers=HEADERS)
        self.assertEqual(response.json(), {'ok': True, 'current_revoked': False})
        self.assertEqual(other.get('/api/portal').status_code, 401)
        replay = TestClient(app); replay.cookies.set(COOKIE_NAME, token)
        self.assertEqual(replay.get('/api/account/sessions').status_code, 401)
        self.assertEqual(self.client.get('/api/portal').status_code, 200)
        self.assertEqual(member.get('/api/portal').status_code, 200)

    def test_ownership_applies_to_admin_and_member(self):
        self.setup_owner()
        member = self.member()
        admin_id = self.listing()['current_session']['id']
        member_id = self.listing(member)['current_session']['id']
        self.assertEqual(self.client.delete('/api/account/sessions/'+member_id, headers=HEADERS).status_code, 404)
        self.assertEqual(member.delete('/api/account/sessions/'+admin_id, headers=HEADERS).status_code, 404)
        self.assertEqual(self.listing()['total_others'], 0)
        self.assertEqual(self.listing(member)['total_others'], 0)

    def test_bulk_revocation_keeps_current_and_removes_only_own_pending_mfa(self):
        self.setup_owner()
        first, second = self.login(), self.login()
        member = self.member()
        with SessionLocal.begin() as db:
            users = {row.username: row.id for row in db.scalars(select(User))}
            for name, user_id in users.items():
                db.add(MFAChallenge(token_hash=token_hash(name), user_id=user_id, expires_at=time.time()+300))
        current_id = self.listing()['current_session']['id']
        response = self.client.post('/api/account/sessions/revoke-others', headers=HEADERS)
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.json()['revoked'], 2)
        self.assertEqual(self.listing()['current_session']['id'], current_id)
        self.assertEqual(self.listing()['total_others'], 0)
        for client in (first, second):
            self.assertEqual(client.get('/api/portal').status_code, 401)
        self.assertEqual(member.get('/api/portal').status_code, 200)
        with SessionLocal() as db:
            self.assertEqual([row.user_id for row in db.scalars(select(MFAChallenge))], [users['devices-member']])

    def test_self_revocation_clears_cookie_and_requires_login(self):
        self.setup_owner()
        token = self.client.cookies.get(COOKIE_NAME)
        current = self.listing()['current_session']['id']
        response = self.client.delete('/api/account/sessions/'+current, headers=HEADERS)
        self.assertEqual(response.json(), {'ok': True, 'current_revoked': True})
        self.assertIsNone(self.client.cookies.get(COOKIE_NAME))
        self.assertEqual(self.client.get('/api/portal').status_code, 401)
        replay = TestClient(app); replay.cookies.set(COOKIE_NAME, token)
        self.assertEqual(replay.get('/api/portal').status_code, 401)

    def test_authentication_mutation_headers_and_unknown_ids(self):
        self.assertEqual(self.client.get('/api/account/sessions').status_code, 401)
        self.setup_owner()
        current = self.listing()['current_session']['id']
        self.assertEqual(self.client.delete('/api/account/sessions/'+current).status_code, 403)
        self.assertEqual(self.client.post('/api/account/sessions/revoke-others').status_code, 403)
        self.assertEqual(self.client.delete('/api/account/sessions/'+str(uuid4()), headers=HEADERS).status_code, 404)
        self.assertEqual(self.client.get('/api/account/sessions?limit=1000').status_code, 422)
        self.assertEqual(self.client.get('/api/account/sessions?offset=-1').status_code, 422)
        self.assertEqual(self.client.get('/api/portal').status_code, 200)

    def test_expired_sessions_are_hidden_and_cannot_be_revoked_as_live_device(self):
        self.setup_owner()
        other = self.login()
        current = self.listing(other)['current_session']['id']
        with SessionLocal.begin() as db:
            db.scalar(select(LoginSession).where(LoginSession.public_id == current)).expires_at = time.time()-1
        self.assertEqual(self.listing()['total_others'], 0)
        self.assertEqual(self.client.delete('/api/account/sessions/'+current, headers=HEADERS).status_code, 404)
        self.assertEqual(other.get('/api/account/sessions').status_code, 401)

    def test_activity_throttling_updates_ip_without_extending_expiry(self):
        self.setup_owner()
        now = time.time()
        token = token_hash(self.client.cookies.get(COOKIE_NAME))
        with SessionLocal.begin() as db:
            row = db.get(LoginSession, token)
            row.last_seen_at = now - 120
            expiry = row.expires_at
        self.client.headers.update({'X-Real-IP':'192.0.2.30', 'User-Agent': CHROME})
        with patch('app.services.auth.time.time', return_value=now):
            self.client.get('/api/auth/status')
        self.client.headers.update({'X-Real-IP':'192.0.2.40'})
        with patch('app.services.auth.time.time', return_value=now+30):
            self.client.get('/api/auth/status')
        with SessionLocal() as db:
            row = db.get(LoginSession, token)
            self.assertEqual((row.last_seen_at, row.ip_address, row.expires_at), (now, '192.0.2.30', expiry))
        with patch('app.services.auth.time.time', return_value=now+61):
            self.client.get('/api/auth/status')
        with SessionLocal() as db:
            row = db.get(LoginSession, token)
            self.assertEqual((row.last_seen_at, row.ip_address, row.expires_at), (now+61, '192.0.2.40', expiry))

    def test_existing_session_schema_upgrade_preserves_cookie_and_expiry(self):
        self.setup_owner()
        token = token_hash(self.client.cookies.get(COOKIE_NAME))
        with SessionLocal() as db:
            row = db.get(LoginSession, token)
            values = {'token': token, 'user_id': row.user_id, 'created': row.created_at, 'expires': row.expires_at}
        with engine.begin() as connection:
            connection.execute(text('DROP TABLE dock_user_sessions'))
            connection.execute(text('CREATE TABLE dock_user_sessions (token_hash VARCHAR(64) PRIMARY KEY, user_id INTEGER NOT NULL REFERENCES dock_users(id), created_at FLOAT NOT NULL, expires_at FLOAT NOT NULL)'))
            connection.execute(text('INSERT INTO dock_user_sessions VALUES (:token,:user_id,:created,:expires)'), values)
        migrate()
        first = self.listing()['current_session']
        migrate()
        second = self.listing()['current_session']
        self.assertEqual(first, second)
        self.assertEqual((first['created_at'], first['expires_at']), (values['created'], values['expires']))
        UUID(first['id'])
        self.assertEqual(self.client.get('/api/portal').status_code, 200)

    def test_pagination_keeps_current_separate_and_has_no_duplicates(self):
        self.setup_owner()
        for _ in range(6):
            self.login()
        first = self.listing()
        second = self.client.get('/api/account/sessions?offset=5&limit=5').json()
        self.assertEqual((first['total_others'], len(first['items']), len(second['items'])), (6, 5, 1))
        ids = [item['id'] for item in first['items'] + second['items']]
        self.assertEqual(len(set(ids)), 6)
        self.assertNotIn(first['current_session']['id'], ids)

    def test_mfa_pending_login_is_not_a_device_until_second_factor_completes(self):
        self.setup_owner()
        secret = pyotp.random_base32()
        with SessionLocal.begin() as db:
            db.scalar(select(User)).totp_secret = cipher().encrypt(secret.encode()).decode()
        other = self.login()
        self.assertIsNotNone(other.cookies.get(MFA_COOKIE))
        self.assertEqual(other.get('/api/account/sessions').status_code, 401)
        self.assertEqual(self.listing()['total_others'], 0)
        response = other.post('/api/auth/mfa', json={'code': pyotp.TOTP(secret).now()}, headers=HEADERS)
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(self.listing(other)['current_session']['label'], 'Safari · iOS')
        self.assertEqual(self.listing()['total_others'], 1)

    def test_device_labels_use_known_names_and_store_bounded_untrusted_headers(self):
        self.assertEqual(device_details(CHROME+' Edg/131.0')['label'], 'Edge · Windows')
        self.assertEqual(device_details('Mozilla/5.0 (iPad; CPU OS 18) Mobile/1 Safari/1')['kind'], 'tablet')
        self.assertEqual(device_details('<script>alert(1)</script>')['label'], '기기 정보 없음')
        self.client.headers.update({'User-Agent': 'x'*2000, 'X-Real-IP':'invalid-ip', 'X-Forwarded-For':'192.0.2.99'})
        self.setup_owner()
        current = self.listing()['current_session']
        self.assertEqual((current['label'], current['ip_address']), ('기기 정보 없음', 'unknown'))
        with SessionLocal() as db:
            self.assertEqual(len(db.scalar(select(LoginSession)).user_agent), 512)
