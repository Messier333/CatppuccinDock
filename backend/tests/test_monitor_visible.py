import time
import unittest
from concurrent.futures import Future
from threading import Event, Lock
from unittest.mock import patch

from fastapi.testclient import TestClient
from sqlalchemy import text

import test_auth as legacy
from test_auth import HEADERS
from app.main import app
from app.db.migrations import migrate
from app.db.models import ServiceMonitor, SharedLink, SharedPlacement
from app.db.session import SessionLocal, engine
from app.services import monitoring


class VisibleMonitorTests(unittest.TestCase):
    setUp = legacy.AuthenticationTests.setUp
    tearDown = legacy.AuthenticationTests.tearDown
    setup_owner = legacy.AuthenticationTests.setup_owner

    def links(self, client=None):
        return [link for category in (client or self.client).get('/api/portal').json()['tabs'][0]['categories'] for link in category['links']]

    def add_monitor(self, link, **overrides):
        with SessionLocal.begin() as db:
            row = ServiceMonitor(name=link['name'], link_url=link['url'], check_url=link['url'],
                                 revision='test', **overrides)
            db.add(row); db.flush()
            return row.id

    def refresh(self, ids, client=None):
        return (client or self.client).post('/api/bookmark-status/refresh', json={'bookmark_ids': ids}, headers=HEADERS)

    def test_only_requested_expired_enabled_monitors_are_queued_and_old_colors_remain(self):
        self.setup_owner(); links = self.links(); now = time.time()
        stale = self.add_monitor(links[0], state='down', checked_at=now-86400, next_check=0)
        self.add_monitor(links[1], state='up', checked_at=now-86400, next_check=0)
        self.add_monitor(links[2], state='up', checked_at=now, next_check=now+300)
        self.add_monitor(links[3], enabled=False)
        with patch('app.api.monitoring.queue_checks', return_value={stale: Future()}) as queue:
            response = self.refresh([links[i]['id'] for i in (0, 2, 3)])
            self.assertEqual(response.status_code, 200, response.text)
            result = response.json(); queue.assert_called_once_with({stale})
            self.assertTrue(result['refreshing'])
            self.assertEqual(set(result['statuses']), {links[0]['id'], links[2]['id']})
            self.assertEqual(result['statuses'][links[0]['id']]['state'], 'down')
            cached = self.client.get('/api/bookmark-status').json()
            self.assertEqual(cached[links[1]['id']]['state'], 'up')
            self.assertEqual(cached[links[0]['id']]['checked_at'], now-86400)

    def test_members_can_refresh_owned_links_but_not_foreign_disabled_or_revoked_shared_links(self):
        self.setup_owner(); owner_link = self.links()[0]; self.add_monitor(owner_link)
        self.client.post('/api/admin/users', json={'username':'visible-member','password':'a-member-password'}, headers=HEADERS)
        member = TestClient(app)
        member.post('/api/auth/login', json={'username':'visible-member','password':'a-member-password'}, headers=HEADERS)
        own = self.links(member)[0]
        with SessionLocal.begin() as db:
            shared = SharedLink(name='Managed', url='https://new-shared.test/', icon='world', icon_color='auto', source_name='Fixture', published=True)
            db.add(shared); db.flush(); sid = shared.id
            db.add(SharedPlacement(bookmark_id=own['id'], link_id=sid))
        mid = self.add_monitor({**own, 'url':'https://new-shared.test/'})
        with patch('app.api.monitoring.queue_checks', return_value={mid:Future()}) as queue:
            result = self.refresh([own['id'], owner_link['id'], 'missing'], member).json()
            queue.assert_called_once_with({mid}); self.assertEqual(set(result['statuses']), {own['id']})
        with SessionLocal.begin() as db: db.get(SharedLink, sid).published = False
        with patch('app.api.monitoring.queue_checks') as queue:
            self.assertEqual(self.refresh([own['id'], owner_link['id']], member).json(), {'statuses':{},'refreshing':False})
            queue.assert_not_called()
        self.assertEqual(TestClient(app).post('/api/bookmark-status/refresh', json={'bookmark_ids':[own['id']]}, headers=HEADERS).status_code, 401)
        self.assertEqual(self.client.post('/api/bookmark-status/refresh', json={'bookmark_ids':[own['id']]}).status_code, 403)
        for ids in ([], [own['id']]*201): self.assertEqual(self.refresh(ids).status_code, 422)
        self.assertEqual(self.client.post('/api/bookmark-status/refresh', json={'bookmark_ids':[own['id']], 'url':'http://private.test'}, headers=HEADERS).status_code, 422)

    def test_refresh_returns_cached_state_while_running_deduplicates_and_reuses_fresh_result(self):
        self.setup_owner(); link = self.links()[0]
        mid = self.add_monitor(link, state='down', checked_at=time.time()-3600, next_check=0)
        started, release = Event(), Event()
        def probe(*args):
            started.set(); release.wait(5)
            return {'state':'up','http_status':200,'detail':'normal'}
        with patch('app.services.monitoring.check_url', side_effect=probe) as check:
            try:
                response = self.refresh([link['id']]).json()
                self.assertTrue(response['refreshing']); self.assertEqual(response['statuses'][link['id']]['state'], 'down')
                self.assertTrue(started.wait(3))
                for _ in range(3):
                    again = self.refresh([link['id']]).json()
                    self.assertTrue(again['refreshing']); self.assertEqual(again['statuses'][link['id']]['state'], 'down')
                self.assertEqual(check.call_count, 1)
            finally:
                release.set(); monitoring.run_batch([mid])
            result = self.refresh([link['id']]).json()
            self.assertFalse(result['refreshing']); self.assertEqual(result['statuses'][link['id']]['state'], 'up')
            self.assertEqual(check.call_count, 1)
            with SessionLocal.begin() as db: db.get(ServiceMonitor, mid).next_check = 0
            self.refresh([link['id']]); monitoring.run_batch([mid])
            self.assertEqual(check.call_count, 2)

    def test_shared_queue_deduplicates_bursts_and_limits_workers_to_four(self):
        started, release, lock = Event(), Event(), Lock()
        active = peak = 0
        def job(mid):
            nonlocal active, peak
            with lock:
                active += 1; peak = max(peak, active)
                if active == 4: started.set()
            release.wait(5)
            with lock: active -= 1
        with patch('app.services.monitoring.run_check', side_effect=job) as check:
            try:
                first = monitoring.queue_checks(range(200))
                self.assertTrue(started.wait(3)); self.assertEqual(len(first), 200)
                second = monitoring.queue_checks(range(200))
                self.assertTrue(all(first[key] is second[key] for key in first))
                self.assertEqual(check.call_count, 4)
            finally: release.set()
            for future in first.values(): future.result(timeout=5)
            self.assertEqual(peak, 4); self.assertEqual(check.call_count, 200)

    def test_lease_blocks_duplicate_force_checks_recovers_after_expiry_and_rejects_obsolete_results(self):
        self.setup_owner(); mid = self.add_monitor(self.links()[0], state='down', next_check=time.time()+86400, checking_until=time.time()+30)
        with patch('app.services.monitoring.check_url') as check:
            monitoring.run_check(mid, force=True); check.assert_not_called()
        with SessionLocal.begin() as db: db.get(ServiceMonitor, mid).checking_until = time.time()-1
        def probe(*args):
            monitoring.run_check(mid, force=True)
            return {'state':'up','http_status':403,'detail':'auth'}
        with patch('app.services.monitoring.check_url', side_effect=probe) as check:
            monitoring.run_check(mid); self.assertEqual(check.call_count, 1)
            monitoring.run_check(mid); self.assertEqual(check.call_count, 1)
        with SessionLocal.begin() as db:
            row = db.get(ServiceMonitor, mid)
            self.assertEqual(row.checking_until, 0); self.assertGreater(row.next_check, time.time()+86000)
            row.next_check = 0
        def obsolete(*args):
            with SessionLocal.begin() as db:
                row = db.get(ServiceMonitor, mid); row.revision = 'edited'; row.state = 'pending'; row.checking_until = 0
            return {'state':'down','http_status':503,'detail':'old'}
        with patch('app.services.monitoring.check_url', side_effect=obsolete): monitoring.run_check(mid)
        with SessionLocal() as db: self.assertEqual(db.get(ServiceMonitor, mid).state, 'pending')

    def test_upgrade_adds_lease_column_without_changing_existing_monitor(self):
        self.setup_owner(); mid = self.add_monitor(self.links()[0], state='up', checked_at=123, next_check=456)
        with engine.begin() as connection: connection.execute(text('ALTER TABLE dock_service_monitors DROP COLUMN checking_until'))
        migrate(); migrate()
        with SessionLocal() as db:
            row = db.get(ServiceMonitor, mid)
            self.assertEqual((row.state, row.checked_at, row.next_check, row.checking_until), ('up', 123, 456, 0))
