import json
from io import BytesIO
from pathlib import Path
import subprocess
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch
from PIL import Image
from sqlalchemy import select

import test_auth as auth_tests
from test_auth import HEADERS
from app.db.models import Setting
from app.db.session import SessionLocal
from app.services.media import gifdb, gif_search, pixabay_gifs
from app.services.media.gif_optimizer import prepare_video
from app.services.media.remote_media import RemoteMediaError

SLUG='pixel-art-forest-abcd1234'
GIFDB=f'<a href="/gif/{SLUG}.html"><img src="/images/thumbnail/{SLUG}.gif" alt="Pixel Forest GIF"></a>'
VIDEO={'id':125,'tags':'forest, night','user':'Artist','duration':12,'videos':{'tiny':{'url':'https://cdn.pixabay.com/video/2025/01/01/125.mp4','thumbnail':'https://cdn.pixabay.com/video/2025/01/01/125.jpg','width':640,'height':360}}}

class MediaProvidersTests(unittest.TestCase):
 setUp=auth_tests.AuthenticationTests.setUp
 tearDown=auth_tests.AuthenticationTests.tearDown
 setup_owner=auth_tests.AuthenticationTests.setup_owner
 def key(self):
  self.setup_owner()
  config=self.client.get('/api/admin/backgrounds').json();config.pop('has_pixabay_key');config['pixabay_key']='test-pixabay-key'
  self.assertEqual(self.client.put('/api/admin/backgrounds',json=config,headers=HEADERS).status_code,200)
 def test_gifdb_full_text_search_uses_correct_route_and_verified_preview(self):
  with patch('app.services.media.gifdb.page_html',return_value=GIFDB+'<a href="/search/pixel%20art?page=2">Next</a>') as request:
   result=gifdb.search('픽셀아트',1)
   self.assertEqual(request.call_args.args[0],'https://gifdb.com/search/pixel%20art')
   self.assertEqual(result['items'][0]['source']['provider'],'gifdb');self.assertTrue(result['has_more'])
   self.assertEqual(result['items'][0]['id'],SLUG)
  with patch('app.services.media.gifdb.page_html',return_value=GIFDB.replace('href="/gif/','href="https://evil.test/gif/')):
   self.assertEqual(gifdb.search('pixel',1)['items'],[])
 def test_gifdb_resolution_allows_only_the_selected_own_host_gif(self):
  markup=f'<meta property="og:image" content="https://gifdb.com/images/branded/high/{SLUG}.gif"><meta property="og:title" content="Pixel Forest GIF | GIFDB.com">'
  with patch('app.services.media.gifdb.page_html',return_value=markup) as request:
   result=gifdb.resolve(SLUG);self.assertEqual(result['title'],'Pixel Forest')
   self.assertEqual(request.call_args.args[0],f'https://gifdb.com/gif/{SLUG}.html')
  for html in (markup.replace('gifdb.com/images','localhost/images'),markup.replace(SLUG,'another-gif'),'<html>No media</html>'):
   with patch('app.services.media.gifdb.page_html',return_value=html):
    with self.assertRaises(RemoteMediaError):gifdb.resolve(SLUG)
  with patch('app.services.media.gifdb.page_html') as request:
   for identifier in ('../private','https://localhost/file','a'*161):
    with self.assertRaises(RemoteMediaError):gifdb.resolve(identifier)
   request.assert_not_called()
 def test_aggregate_search_keeps_successful_results_when_one_provider_fails(self):
  self.setup_owner();gif_search.cache.clear()
  with patch('app.services.media.gifdb.search',return_value={'items':[],'has_more':False}),patch('app.services.media.wallpaper_gifs.search',side_effect=lambda provider,*args: {'items':[{'id':'42','source':{'provider':provider}}],'has_more':True} if provider=='alphacoders' else (_ for _ in ()).throw(RemoteMediaError('offline'))):
   result=gif_search.search('all','pixel',1)
  self.assertEqual(len(result['items']),1);self.assertEqual(result['unavailable'],['MotionBgs']);self.assertTrue(result['has_more'])
 def test_pixabay_key_is_required_and_search_responses_survive_restart_for_24_hours(self):
  self.setup_owner()
  self.assertEqual(self.client.get('/api/backgrounds/search?provider=pixabay&q=nature').status_code,409)
  config=self.client.get('/api/admin/backgrounds').json();config.pop('has_pixabay_key');config['pixabay_key']='test-pixabay-key'
  self.client.put('/api/admin/backgrounds',json=config,headers=HEADERS)
  with patch('app.services.media.pixabay_gifs.fetch_public',return_value=json.dumps({'hits':[VIDEO],'totalHits':60}).encode()) as fetch:
   first=pixabay_gifs.search('숲',1);second=pixabay_gifs.search('숲',1)
   self.assertEqual(first,second);self.assertEqual(fetch.call_count,1)
   self.assertIn('q=forest',fetch.call_args.args[0]);self.assertTrue(first['has_more'])
   self.assertEqual(first['items'][0]['media_type'],'video');self.assertNotIn('url',first['items'][0])
  gif_search.cache.clear()
  with patch('app.services.media.pixabay_gifs.fetch_public') as fetch:
   self.assertEqual(pixabay_gifs.search('숲',1),first);fetch.assert_not_called()
  with SessionLocal() as db:
   for row in db.scalars(select(Setting).where(Setting.key.like('pixabay-search:%'))):self.assertNotIn('test-pixabay-key',str(row.value))
 def test_pixabay_ignores_untrusted_media_urls_and_resolution_is_id_bound(self):
  self.key()
  with patch('app.services.media.pixabay_gifs.request',return_value={'hits':[VIDEO]}):self.assertEqual(pixabay_gifs.resolve('125')['id'],'125')
  self.assertIsNone(pixabay_gifs.item(VIDEO|{'videos':{'tiny':VIDEO['videos']['tiny']|{'url':'https://localhost/private.mp4'}}}))
  with patch('app.services.media.pixabay_gifs.request') as request:
   for identifier in ('../private','https://localhost','1'*13):
    with self.assertRaises(Exception):pixabay_gifs.resolve(identifier)
   request.assert_not_called()
 def test_video_converts_to_animated_local_gif_without_network(self):
  with TemporaryDirectory() as directory:
   path=Path(directory)/'fixture.mp4'
   subprocess.run(['ffmpeg','-nostdin','-v','error','-f','lavfi','-i','testsrc2=size=160x90:rate=10','-t','2','-c:v','mpeg4','-threads','1',str(path)],check=True)
   output=prepare_video(path.read_bytes())
   self.key()
   source=pixabay_gifs.item(VIDEO)['source']
   with patch('app.services.media.gif_search.download',return_value=(path.read_bytes(),'Forest video',source)):
    imported=self.client.post('/api/backgrounds/import',json={'provider':'pixabay','item_id':'125'},headers=HEADERS)
   self.assertEqual(imported.status_code,200,imported.text)
   image=imported.json()
   self.assertEqual(image['source']['provider'],'pixabay')
   self.assertTrue(self.client.get('/api/backgrounds/'+image['id']+'/content').content.startswith(b'GIF89a'))
   document=self.client.post('/api/backups/export',json={},headers=HEADERS).json()
   self.assertEqual(self.client.post('/api/backups/import-preview',json={'document':document},headers=HEADERS).status_code,200)
  self.assertLess(len(output),10*1024*1024)
  with Image.open(BytesIO(output)) as image:
   self.assertEqual(image.size,(160,90));self.assertGreater(image.n_frames,1);self.assertEqual(image.info['loop'],0)
   durations=[]
   for index in range(image.n_frames):image.seek(index);durations.append(image.info['duration'])
   self.assertEqual(sum(durations),2000)
