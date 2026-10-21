from io import BytesIO
import asyncio
from types import SimpleNamespace
import time
import unittest
from unittest.mock import patch
from fastapi import HTTPException
from fastapi.testclient import TestClient
from sqlalchemy import select

import test_auth as auth_tests
from test_auth import HEADERS
from test_backgrounds import gif
from app.db.migrations import migrate
from app.db.models import BackgroundImage,BackgroundTransfer,Setting,User
from app.db.session import SessionLocal
from app.main import app
from app.api.backgrounds import upload
from app.services.media import gif_search, media_policy
from app.services.media.remote_media import RemoteMediaError

SOURCE={'provider':'commons','item_id':'42','title':'Public rain','page_url':'https://commons.wikimedia.org/?curid=42','author':'Artist','license':'CC0','license_url':None}

class MediaPolicyTests(unittest.TestCase):
 setUp=auth_tests.AuthenticationTests.setUp
 tearDown=auth_tests.AuthenticationTests.tearDown
 setup_owner=auth_tests.AuthenticationTests.setup_owner
 def member(self):
  self.setup_owner()
  self.client.post('/api/admin/users',json={'username':'media-member','password':'a-media-member-password'},headers=HEADERS)
  client=TestClient(app)
  self.assertEqual(client.post('/api/auth/login',json={'username':'media-member','password':'a-media-member-password'},headers=HEADERS).status_code,200)
  return client
 def configure(self,**changes):
  config=self.client.get('/api/admin/backgrounds').json();config.pop('has_pixabay_key');config.update(changes)
  response=self.client.put('/api/admin/backgrounds',json=config,headers=HEADERS)
  self.assertEqual(response.status_code,200,response.text)
  return response
 def load(self,client,item='42'):
  return client.post('/api/backgrounds/import',json={'provider':'commons','item_id':item},headers=HEADERS)
 def use(self,client,item='42',color='red'):
  source=SOURCE|{'item_id':item}
  with patch('app.services.media.gif_search.download',return_value=(gif(color),'Public rain',source)) as download:
   result=self.load(client,item)
  self.assertEqual(result.status_code,200,result.text)
  return result.json(),download.call_count
 def test_admin_settings_are_private_encrypted_and_key_can_be_retained_and_removed(self):
  member=self.member()
  self.assertEqual(member.get('/api/admin/backgrounds').status_code,403)
  self.assertEqual(member.put('/api/admin/backgrounds',json={},headers=HEADERS).status_code,403)
  self.assertEqual(self.client.put('/api/admin/backgrounds',json={}).status_code,403)
  self.configure(pixabay_key='test-pixabay-credential')
  self.assertNotIn('test-pixabay-credential',self.client.get('/api/admin/backgrounds').text)
  self.assertNotIn('test-pixabay-credential',member.get('/api/backgrounds/providers').text)
  with SessionLocal() as db:self.assertNotIn('test-pixabay-credential',str(db.get(Setting,'media-policy').value))
  self.configure(member_per_day=3)
  self.assertEqual(media_policy.provider_key('pixabay'),'test-pixabay-credential')
  self.configure(clear_pixabay_key=True)
  self.assertEqual(media_policy.provider_key('pixabay'),'')
 def test_same_owned_provider_item_reuses_saved_file_without_download_or_extra_charge(self):
  member=self.member();first,calls=self.use(member)
  self.assertEqual(calls,1)
  second,calls=self.use(member)
  self.assertEqual(calls,0);self.assertEqual(first,second)
  usage=member.get('/api/backgrounds').json()['usage']
  self.assertEqual(usage['today_count'],1);self.assertEqual(usage['today_bytes'],len(gif()))
  with patch('app.services.media.gif_search.download') as download:
   self.assertEqual(self.load(member,'43').status_code,429)
   download.assert_not_called()
 def test_failure_charges_received_bytes_and_persists_across_restart_and_login(self):
  member=self.member()
  def fail(*args,**kwargs):kwargs['on_chunk'](12345);raise RemoteMediaError('upstream failed')
  with patch('app.services.media.gif_search.download',side_effect=fail):self.assertEqual(self.load(member).status_code,502)
  usage=member.get('/api/backgrounds').json()['usage'];self.assertEqual((usage['today_count'],usage['today_bytes']),(1,12345))
  gif_search.budgets.clear();migrate()
  member.post('/api/auth/logout',headers=HEADERS)
  member.post('/api/auth/login',json={'username':'media-member','password':'a-media-member-password'},headers=HEADERS)
  with patch('app.services.media.gif_search.download') as download:
   self.assertEqual(self.load(member).status_code,429);download.assert_not_called()
  with SessionLocal() as db:self.assertFalse(db.scalar(select(BackgroundTransfer)).pending)
 def test_daily_attempts_survive_deletion_and_reset_at_portal_timezone_midnight(self):
  member=self.member();self.configure(member_per_day=2)
  now=time.time()
  with patch('app.services.media.media_policy.clock',return_value=now):first,_=self.use(member)
  with patch('app.services.media.media_policy.clock',return_value=now+61):second,_=self.use(member,'43','green')
  for image in (first,second):self.assertEqual(member.delete('/api/backgrounds/'+image['id'],headers=HEADERS).status_code,200)
  with patch('app.services.media.media_policy.clock',return_value=now+122),patch('app.services.media.gif_search.download') as download:
   self.assertEqual(self.load(member,'44').status_code,429);download.assert_not_called()
  with patch('app.services.media.media_policy.clock',return_value=now+86401):
   self.use(member,'44','yellow');self.assertEqual(member.get('/api/backgrounds').json()['usage']['today_count'],1)
 def test_upload_and_download_share_the_same_quota(self):
  member=self.member()
  response=member.post('/api/backgrounds',content=gif(),headers=HEADERS|{'Content-Type':'image/gif'})
  self.assertEqual(response.status_code,200,response.text)
  with patch('app.services.media.gif_search.download') as download:
   self.assertEqual(self.load(member).status_code,429);download.assert_not_called()
 def test_disabled_actions_do_not_fetch_or_optimize_and_categories_still_work(self):
  member=self.member();self.configure(member_import=False,member_upload=False)
  with patch('app.services.media.gif_search.download') as download,patch('app.api.backgrounds.prepare_gif') as optimize:
   self.assertEqual(self.load(member).status_code,403)
   self.assertEqual(member.post('/api/backgrounds',content=gif(),headers=HEADERS|{'Content-Type':'image/gif'}).status_code,403)
   download.assert_not_called();optimize.assert_not_called()
  tab=member.post('/api/tabs',json={'name':'Allowed tab'},headers=HEADERS)
  self.assertEqual(tab.status_code,200)
  self.assertEqual(member.post('/api/categories',json={'name':'Allowed category','tab_id':tab.json()['id']},headers=HEADERS).status_code,200)
  self.assertFalse(member.get('/api/backgrounds').json()['usage']['allow_upload'])
 def test_full_library_is_rejected_before_network_or_optimizer(self):
  member=self.member()
  with SessionLocal.begin() as db:
   user=db.scalar(select(User).where(User.username=='media-member'))
   for index in range(20):db.add(BackgroundImage(user_id=user.id,name=str(index),sha256=f'{index:064x}',byte_size=len(gif()),width=64,height=48,frames=2,data=gif()))
  with patch('app.services.media.gif_search.download') as download,patch('app.api.backgrounds.prepare_gif') as optimize:
   self.assertEqual(self.load(member).status_code,409)
   self.assertEqual(member.post('/api/backgrounds',content=gif(),headers=HEADERS|{'Content-Type':'image/gif'}).status_code,409)
   download.assert_not_called();optimize.assert_not_called()
 def test_verified_public_cache_can_be_reused_across_users_without_exposing_private_image(self):
  member=self.member();admin_image,_=self.use(self.client)
  image,calls=self.use(member)
  self.assertEqual(calls,0);self.assertNotEqual(image['id'],admin_image['id'])
  self.assertEqual(member.get('/api/backgrounds/'+admin_image['id']+'/content').status_code,404)
  usage=member.get('/api/backgrounds').json()['usage'];self.assertEqual((usage['today_count'],usage['today_bytes']),(1,0))
 def test_storage_limits_block_network_and_pending_reservations_serialize_transfers(self):
  member=self.member();self.configure(member_storage_mb=10)
  with SessionLocal.begin() as db:
   user=db.scalar(select(User).where(User.username=='media-member'))
   for index in range(2):db.add(BackgroundImage(user_id=user.id,name=str(index),sha256=f'{index:064x}',byte_size=6*1024*1024,width=64,height=48,frames=2,data=gif()))
  with patch('app.services.media.gif_search.download') as download:
   self.assertEqual(self.load(member).status_code,409);download.assert_not_called()
  with SessionLocal() as db:admin=db.scalar(select(User).where(User.role=='admin'))
  with media_policy.transfer(admin,'import') as job:
   with self.assertRaises(HTTPException) as error:
    with media_policy.transfer(admin,'upload'):pass
   self.assertEqual(error.exception.status_code,503)
   with SessionLocal() as db:self.assertEqual(db.scalar(select(BackgroundTransfer)).charged_bytes,100*1024*1024)
   job.progress(512)
  with SessionLocal() as db:
   row=db.scalar(select(BackgroundTransfer));self.assertEqual(row.charged_bytes,512);self.assertFalse(row.pending)
 def test_remaining_daily_bytes_bound_the_download_before_it_starts(self):
  member=self.member();self.configure(member_daily_mb=1)
  with patch('app.services.media.gif_search.download',return_value=(gif(),'Public rain',SOURCE)) as download:
   self.assertEqual(self.load(member).status_code,200)
   self.assertEqual(download.call_args.kwargs['max_bytes'],1024*1024)
 def test_client_supplied_source_metadata_never_creates_shared_cache(self):
  member=self.member()
  with SessionLocal.begin() as db:
   admin=db.scalar(select(User).where(User.role=='admin'))
   db.add(BackgroundImage(user_id=admin.id,name='Private file',sha256='f'*64,byte_size=len(gif()),width=64,height=48,frames=2,data=gif('green'),source=SOURCE))
  image,calls=self.use(member)
  self.assertEqual(calls,1)
  self.assertEqual(member.get('/api/backgrounds/'+image['id']+'/content').content,gif())
 def test_backup_restore_obeys_server_storage_cap(self):
  member=self.member()
  image,_=self.use(self.client)
  document=self.client.post('/api/backups/export',json={},headers=HEADERS).json()
  preview=member.post('/api/backups/import-preview',json={'document':document},headers=HEADERS)
  self.assertEqual(preview.status_code,200,preview.text)
  self.configure(server_storage_mb=10)
  with SessionLocal.begin() as db:
   row=db.get(BackgroundImage,image['id']);row.byte_size=10*1024*1024
  response=member.post('/api/backups/import',json={'preview_id':preview.json()['preview_id'],'mode':'merge'},headers=HEADERS)
  self.assertEqual(response.status_code,409,response.text)
  self.assertEqual(member.get('/api/backgrounds').json()['items'],[])
 def test_slow_upload_times_out_and_releases_reservation_with_partial_bytes_charged(self):
  member=self.member()
  with SessionLocal() as db:user=db.scalar(select(User).where(User.username=='media-member'))
  async def stream():
   yield b'GIF89a'
   await asyncio.sleep(5)
  request=SimpleNamespace(headers={'content-type':'image/gif'},stream=stream)
  with patch('app.api.backgrounds.UPLOAD_TIMEOUT',0.03):
   with self.assertRaises(HTTPException) as error:asyncio.run(upload(request,user))
  self.assertEqual(error.exception.status_code,408)
  usage=member.get('/api/backgrounds').json()['usage'];self.assertEqual((usage['today_count'],usage['today_bytes']),(1,6))
  with SessionLocal() as db:self.assertFalse(db.scalar(select(BackgroundTransfer)).pending)
