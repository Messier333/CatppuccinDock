import time
import unittest

import pyotp
from fastapi.testclient import TestClient
from sqlalchemy import func, select

import test_auth as legacy_tests
from test_auth import CREDENTIALS, HEADERS
from app.services.auth import COOKIE_NAME
from app.db.session import Base, SessionLocal, engine
from app.main import app
from app.db.migrations import migrate
from app.db.models import Bookmark, LegacySession, LoginSession, MFAChallenge, Owner, RecoveryCode, TOTPEnrollment, User
from app.core.security import cipher, hash_password, token_hash


class FeatureTests(unittest.TestCase):
    setUp = legacy_tests.AuthenticationTests.setUp
    tearDown = legacy_tests.AuthenticationTests.tearDown
    setup_owner = legacy_tests.AuthenticationTests.setup_owner

    def member(self):
        response = self.client.post('/api/admin/users', json={'username':'member', 'password':'a-member-password', 'role':'member'}, headers=HEADERS)
        self.assertEqual(response.status_code, 200, response.text)
        other = TestClient(app)
        self.assertEqual(other.post('/api/auth/login', json={'username':'member','password':'a-member-password'}, headers=HEADERS).status_code, 200)
        return other, response.json()['id']

    def enable_2fa(self):
        response = self.client.post('/api/account/2fa/enroll', json={'password':CREDENTIALS['password']}, headers=HEADERS)
        self.assertEqual(response.status_code,200,response.text)
        secret = response.json()['secret']
        self.assertIn('<svg',response.json()['qr_svg'])
        response = self.client.post('/api/account/2fa/confirm', json={'code':pyotp.TOTP(secret).now()}, headers=HEADERS)
        self.assertEqual(response.status_code,200,response.text)
        self.assertEqual(len(response.json()['recovery_codes']),10)
        return secret,response.json()['recovery_codes']

    def test_members_cannot_access_administration(self):
        self.setup_owner()
        other,_ = self.member()
        for endpoint in ('users','settings','sso','me'):
            self.assertEqual(other.get('/api/admin/'+endpoint).status_code,403)
        self.assertEqual(other.post('/api/admin/users',json={'username':'attacker','password':'a-member-password'},headers=HEADERS).status_code,403)
        self.assertEqual(other.put('/api/admin/settings',json={},headers=HEADERS).status_code,403)
        self.assertEqual(other.get('/api/account').status_code,200)

    def test_bookmarks_are_isolated_and_parent_ownership_is_checked(self):
        self.setup_owner()
        own=self.client.get('/api/portal').json()['tabs'][0]
        category=own['categories'][0]
        bookmark=category['links'][0]
        other,_=self.member()
        self.assertEqual(other.get('/api/bookmarks/'+bookmark['id']).status_code,404)
        self.assertEqual(other.delete('/api/bookmarks/'+bookmark['id'],headers=HEADERS).status_code,404)
        data={'category_id':category['id'],'name':'Private','url':'https://example.com'}
        self.assertEqual(other.post('/api/bookmarks',json=data,headers=HEADERS).status_code,404)
        own_other=other.get('/api/portal').json()['tabs'][0]['categories'][0]
        own_other_link=own_other['links'][0]
        self.assertEqual(other.put('/api/bookmarks/'+own_other_link['id'],json=data,headers=HEADERS).status_code,404)
        self.assertEqual(other.put('/api/categories/'+own_other['id'],json={'name':'Moved','tab_id':own['id']},headers=HEADERS).status_code,404)
        self.assertEqual(other.delete('/api/tabs/'+own['id'],headers=HEADERS).status_code,404)

    def test_bookmark_crud_order_validation_and_cascade(self):
        self.setup_owner()
        tab=self.client.post('/api/tabs',json={'name':'Mine','banner':'banner_07','position':0},headers=HEADERS).json()['id']
        category=self.client.post('/api/categories',json={'name':'Tools','tab_id':tab},headers=HEADERS).json()['id']
        data={'category_id':category,'name':'Portal','url':'http://192.168.1.9:8090','position':3,'icon':'world','icon_color':'#89b4fa'}
        response=self.client.post('/api/bookmarks',json=data,headers=HEADERS)
        self.assertEqual(response.status_code,200,response.text)
        bookmark=response.json()['id']
        for invalid in ({'url':'javascript:alert(1)'},{'url':'file:///etc/passwd'},{'icon_color':'red'},{'name':'  '},{'user_id':2}):
            self.assertEqual(self.client.put('/api/bookmarks/'+bookmark,json={**data,**invalid},headers=HEADERS).status_code,422)
        self.assertEqual(self.client.put('/api/bookmarks/'+bookmark,json={**data,'name':'Updated','position':1},headers=HEADERS).status_code,200)
        self.assertEqual(self.client.get('/api/bookmarks/'+bookmark).json()['name'],'Updated')
        self.assertEqual(self.client.delete('/api/tabs/'+tab,headers=HEADERS).status_code,200)
        self.assertEqual(self.client.get('/api/bookmarks/'+bookmark).status_code,404)

    def test_last_tab_cannot_be_deleted(self):
        self.setup_owner()
        tabs=self.client.get('/api/portal').json()['tabs']
        for tab in tabs[:-1]:
            self.assertEqual(self.client.delete('/api/tabs/'+tab['id'],headers=HEADERS).status_code,200)
        self.assertEqual(self.client.delete('/api/tabs/'+tabs[-1]['id'],headers=HEADERS).status_code,409)

    def test_last_admin_is_preserved_and_deactivation_revokes_sessions(self):
        self.setup_owner()
        self.assertEqual(self.client.put('/api/admin/users/1',json={'username':CREDENTIALS['username'],'role':'member'},headers=HEADERS).status_code,409)
        other,user_id=self.member()
        self.assertEqual(self.client.put(f'/api/admin/users/{user_id}',json={'username':'member','role':'member','active':False},headers=HEADERS).status_code,200)
        self.assertEqual(other.get('/api/portal').status_code,401)
        self.assertEqual(other.post('/api/auth/login',json={'username':'member','password':'a-member-password'},headers=HEADERS).status_code,401)

    def test_global_settings_require_admin_and_persist(self):
        self.setup_owner()
        settings={'search_engine':'g','timezone':'Asia/Seoul','weather_location':'Seoul','temperature_scale':'C'}
        self.assertEqual(self.client.put('/api/admin/settings',json={**settings,'timezone':'invalid/timezone'},headers=HEADERS).status_code,422)
        self.assertEqual(self.client.put('/api/admin/settings',json=settings,headers=HEADERS).status_code,200)
        portal=self.client.get('/api/portal').json()
        self.assertEqual(portal['search']['default'],'g')
        self.assertEqual(portal['clock']['timezone'],'Asia/Seoul')

    def test_password_change_revokes_other_sessions(self):
        self.setup_owner()
        other=TestClient(app)
        other.post('/api/auth/login',json=CREDENTIALS,headers=HEADERS)
        response=self.client.post('/api/account/password',json={'current_password':CREDENTIALS['password'],'new_password':'a-new-long-password'},headers=HEADERS)
        self.assertEqual(response.status_code,200,response.text)
        self.assertEqual(other.get('/api/portal').status_code,401)
        self.assertEqual(self.client.get('/api/portal').status_code,200)
        self.assertEqual(other.post('/api/auth/login',json=CREDENTIALS,headers=HEADERS).status_code,401)

    def test_enrollment_requires_reauthentication_and_encrypts_secret(self):
        self.setup_owner()
        response=self.client.post('/api/account/2fa/enroll',json={'password':'wrong'},headers=HEADERS)
        self.assertEqual(response.status_code,403)
        secret,codes=self.enable_2fa()
        with SessionLocal() as db:
            user=db.get(User,1)
            self.assertNotIn(secret,user.totp_secret)
            self.assertEqual(cipher().decrypt(user.totp_secret.encode()).decode(),secret)
            stored=list(db.scalars(select(RecoveryCode)))
            self.assertEqual(len(stored),10)
            self.assertFalse(any(code.replace('-','')==row.code_hash for code in codes for row in stored))
        profile=self.client.get('/api/account').json()
        self.assertTrue(profile['totp_enabled'])
        self.assertNotIn('totp_secret',profile)

    def test_password_only_login_cannot_access_portal_with_2fa(self):
        self.setup_owner()
        secret,_=self.enable_2fa()
        self.client.post('/api/auth/logout',headers=HEADERS)
        response=self.client.post('/api/auth/login',json=CREDENTIALS,headers=HEADERS)
        self.assertTrue(response.json()['mfa_required'])
        self.assertEqual(self.client.get('/api/portal').status_code,401)
        self.assertFalse(self.client.get('/api/auth/status').json()['authenticated'])
        next_code=pyotp.TOTP(secret).at(time.time()+30)
        response=self.client.post('/api/auth/mfa',json={'code':next_code},headers=HEADERS)
        self.assertEqual(response.status_code,200,response.text)
        self.assertEqual(self.client.get('/api/portal').status_code,200)
        self.client.post('/api/auth/logout',headers=HEADERS)
        self.client.post('/api/auth/login',json=CREDENTIALS,headers=HEADERS)
        self.assertEqual(self.client.post('/api/auth/mfa',json={'code':next_code},headers=HEADERS).status_code,401)

    def test_recovery_codes_are_single_use(self):
        self.setup_owner()
        _,codes=self.enable_2fa()
        for expected in (200,401):
            self.client.post('/api/auth/logout',headers=HEADERS)
            self.client.post('/api/auth/login',json=CREDENTIALS,headers=HEADERS)
            response=self.client.post('/api/auth/mfa',json={'code':codes[0]},headers=HEADERS)
            self.assertEqual(response.status_code,expected,response.text)
        with SessionLocal() as db:
            self.assertEqual(db.scalar(select(func.count()).select_from(RecoveryCode)),9)

    def test_mfa_challenge_expires_and_limits_guesses(self):
        self.setup_owner()
        self.enable_2fa()
        self.client.post('/api/auth/logout',headers=HEADERS)
        self.client.post('/api/auth/login',json=CREDENTIALS,headers=HEADERS)
        for _ in range(5):
            self.assertEqual(self.client.post('/api/auth/mfa',json={'code':'not-a-code'},headers=HEADERS).status_code,401)
        with SessionLocal() as db:
            self.assertEqual(db.scalar(select(func.count()).select_from(MFAChallenge)),0)
        self.client.post('/api/auth/login',json=CREDENTIALS,headers=HEADERS)
        with SessionLocal.begin() as db:
            db.scalar(select(MFAChallenge)).expires_at=time.time()-1
        self.assertEqual(self.client.post('/api/auth/mfa',json={'code':'123456'},headers=HEADERS).status_code,401)

    def test_disable_2fa_and_expired_enrollment(self):
        self.setup_owner()
        _,codes=self.enable_2fa()
        self.assertEqual(self.client.post('/api/account/2fa/disable',json={'password':CREDENTIALS['password'],'code':codes[0]},headers=HEADERS).status_code,200)
        self.assertFalse(self.client.get('/api/account').json()['totp_enabled'])
        response=self.client.post('/api/account/2fa/enroll',json={'password':CREDENTIALS['password']},headers=HEADERS)
        secret=response.json()['secret']
        with SessionLocal.begin() as db:
            db.get(TOTPEnrollment,1).expires_at=time.time()-1
        self.assertEqual(self.client.post('/api/account/2fa/confirm',json={'code':pyotp.TOTP(secret).now()},headers=HEADERS).status_code,409)

    def test_role_changes_revoke_sessions(self):
        self.setup_owner()
        other,user_id=self.member()
        self.assertEqual(self.client.put(f'/api/admin/users/{user_id}',json={'username':'member','role':'admin'},headers=HEADERS).status_code,200)
        self.assertEqual(other.get('/api/portal').status_code,401)
        other.post('/api/auth/login',json={'username':'member','password':'a-member-password'},headers=HEADERS)
        self.assertEqual(other.get('/api/admin/users').status_code,200)


class MigrationTests(unittest.TestCase):
    def test_legacy_account_session_and_bookmarks_survive_repeated_upgrade(self):
        self.assertEqual(engine.dialect.name,'sqlite')
        Base.metadata.drop_all(engine)
        Base.metadata.create_all(engine)
        password_hash=hash_password('legacy-long-password')
        with SessionLocal.begin() as db:
            db.add(Owner(id=1,username='legacy-owner',password_hash=password_hash))
            db.flush()
            db.add(LegacySession(token_hash=token_hash('legacy-session'),owner_id=1,expires_at=time.time()+3600))
        migrate()
        with SessionLocal() as db:
            self.assertEqual(db.get(User,1).role,'admin')
            self.assertEqual(db.get(User,1).password_hash,password_hash)
            self.assertIsNotNone(db.get(LoginSession,token_hash('legacy-session')))
            count=db.scalar(select(func.count()).select_from(Bookmark))
            self.assertGreater(count,0)
        migrate()
        with SessionLocal() as db:
            self.assertEqual(db.scalar(select(func.count()).select_from(Bookmark)),count)
        client=TestClient(app)
        client.cookies.set(COOKIE_NAME,'legacy-session')
        self.assertEqual(client.get('/api/portal').status_code,200)
