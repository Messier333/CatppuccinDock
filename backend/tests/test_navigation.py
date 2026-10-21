import unittest
from fastapi.testclient import TestClient
from sqlalchemy import select
import test_auth as legacy
from test_auth import HEADERS
from app.main import app
from app.db.models import Setting, User
from app.db.session import SessionLocal

class NavigationTests(unittest.TestCase):
    setUp = legacy.AuthenticationTests.setUp
    tearDown = legacy.AuthenticationTests.tearDown
    setup_owner = legacy.AuthenticationTests.setup_owner

    def member(self):
        response=self.client.post('/api/admin/users',json={'username':'nav-member','password':'a-member-password'},headers=HEADERS)
        self.assertEqual(response.status_code,200,response.text)
        client=TestClient(app)
        client.post('/api/auth/login',json={'username':'nav-member','password':'a-member-password'},headers=HEADERS)
        return client,response.json()['id']

    def test_order_is_account_scoped_persistent_and_can_be_reset(self):
        self.setup_owner();member,_=self.member()
        initial=self.client.get('/api/navigation').json()['order']
        reordered=initial[::-1]
        self.assertEqual(self.client.put('/api/navigation',json={'order':reordered},headers=HEADERS).status_code,200)
        self.assertEqual(self.client.get('/api/navigation').json()['order'],reordered)
        member_default=member.get('/api/navigation').json()['order']
        self.assertNotIn('users',member_default)
        self.assertEqual(member.put('/api/navigation',json={'order':member_default[::-1]},headers=HEADERS).status_code,200)
        self.assertEqual(self.client.get('/api/navigation').json()['order'],reordered)
        self.assertEqual(self.client.delete('/api/navigation',headers=HEADERS).status_code,200)
        self.assertEqual(self.client.get('/api/navigation').json()['order'],initial)
        self.assertEqual(member.get('/api/navigation').json()['order'],member_default[::-1])

    def test_missing_duplicate_foreign_and_admin_menu_ids_cannot_be_saved(self):
        self.setup_owner();member,_=self.member()
        defaults=member.get('/api/navigation').json()['order']
        for order in (defaults[:-1],defaults+[defaults[0]],defaults+['users'],defaults+['unknown']):
            response=member.put('/api/navigation',json={'order':order},headers=HEADERS)
            self.assertEqual(response.status_code,409,response.text)
            self.assertEqual(member.get('/api/navigation').json()['order'],defaults)
        self.assertEqual(member.put('/api/navigation',json={'order':defaults,'user_id':1},headers=HEADERS).status_code,422)
        self.assertEqual(member.put('/api/navigation',json={'order':defaults}).status_code,403)
        self.assertEqual(member.delete('/api/navigation').status_code,403)
        outsider=TestClient(app)
        self.assertEqual(outsider.get('/api/navigation').status_code,401)
        self.assertEqual(outsider.put('/api/navigation',json={'order':defaults},headers=HEADERS).status_code,401)

    def test_obsolete_and_role_ineligible_saved_ids_are_filtered_and_new_items_appended(self):
        self.setup_owner();member,uid=self.member()
        with SessionLocal.begin() as db:
            db.add(Setting(key=f'navigation:{uid}',value={'order':['security','users','obsolete','security']}))
        result=member.get('/api/navigation').json()['order']
        self.assertEqual(result[0],'security');self.assertEqual(len(result),len(set(result)))
        self.assertNotIn('users',result);self.assertNotIn('obsolete',result);self.assertIn('bookmarks',result)

    def test_new_sso_section_preserves_legacy_order_and_is_admin_only(self):
        self.setup_owner();member,_=self.member()
        initial=self.client.get('/api/navigation').json()['order']
        self.assertIn('sso',initial)
        self.assertNotIn('sso',member.get('/api/navigation').json()['order'])
        with SessionLocal.begin() as db:
            owner_id=db.scalar(select(User.id).where(User.role=='admin'))
            db.add(Setting(key=f'navigation:{owner_id}',value={'order':[item for item in reversed(initial) if item!='sso']}))
        restored=self.client.get('/api/navigation').json()['order']
        self.assertEqual(restored[:-1],[item for item in reversed(initial) if item!='sso'])
        self.assertEqual(restored[-1],'sso')
