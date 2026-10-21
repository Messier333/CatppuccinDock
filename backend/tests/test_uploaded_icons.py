import base64
from http.server import BaseHTTPRequestHandler, HTTPServer
from io import BytesIO
import os
from threading import Thread
import unittest
from unittest.mock import patch

from fastapi.testclient import TestClient
from PIL import Image
from sqlalchemy import select

import test_auth as legacy
from test_auth import HEADERS
from test_media_storage import FakeS3
from app.db.models import MediaObjectDeletion, SharedLink, UploadedIcon
from app.db.session import SessionLocal
from app.main import app
from app.services.media import storage, uploaded_icons
from app.api.uploaded_icons import upload_slot


def picture(fmt='PNG', color='red'):
    image = Image.new('RGBA' if fmt in ('PNG', 'WEBP', 'ICO') else 'RGB', (64, 32), color)
    stream = BytesIO(); image.save(stream, format=fmt); return stream.getvalue()


class UploadedIconTests(unittest.TestCase):
    setUp = legacy.AuthenticationTests.setUp
    tearDown = legacy.AuthenticationTests.tearDown
    setup_owner = legacy.AuthenticationTests.setup_owner

    def upload(self, data=None, client=None, name='custom.png'):
        return (client or self.client).post('/api/uploaded-icons', content=picture() if data is None else data,
            headers=HEADERS | {'Content-Type':'application/octet-stream', 'X-File-Name':name})

    def asset(self, **kwargs):
        response = self.upload(**kwargs)
        self.assertEqual(response.status_code, 200, response.text)
        return response.json()

    def member(self):
        credentials = {'username':'icon-member', 'password':'a-member-password'}
        self.client.post('/api/admin/users', json=credentials, headers=HEADERS)
        client = TestClient(app); client.post('/api/auth/login', json=credentials, headers=HEADERS)
        return client

    def bookmark(self, icon, client=None, url='https://uploaded.test'):
        client = client or self.client
        category = client.get('/api/portal').json()['tabs'][0]['categories'][0]['id']
        return client.post('/api/bookmarks', json={'name':'Uploaded bookmark', 'url':url, 'icon':icon, 'category_id':category}, headers=HEADERS)

    def test_formats_become_static_png_with_transparent_padding_and_original_color(self):
        self.setup_owner()
        for fmt in ('PNG','JPEG','WEBP','GIF','ICO'):
            with self.subTest(fmt=fmt):
                item = self.asset(data=picture(fmt), name='my-icon.'+fmt.lower())
                response = self.client.get('/api/uploaded-icons/'+item['id']+'/content')
                self.assertEqual(response.headers['content-type'], 'image/png')
                with Image.open(BytesIO(response.content)) as image:
                    self.assertEqual((image.format, image.size), ('PNG',(128,128)))
                    self.assertEqual(image.getpixel((0,0))[3], 0)
                    pixel = image.getpixel((64,64)); self.assertGreater(pixel[0], 240); self.assertLess(pixel[1], 20)
        svg = b'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24"><defs><linearGradient id="g"><stop stop-color="red"/><stop offset="1" stop-color="blue"/></linearGradient></defs><path fill="url(#g)" d="M0 0h24v24H0z"/></svg>'
        self.assertTrue(self.asset(data=svg, name='gradient.svg')['icon'].startswith('upload:'))

    def test_private_content_auth_etag_and_no_storage_credentials_in_metadata(self):
        self.setup_owner(); item = self.asset(); member = self.member()
        path = '/api/uploaded-icons/'+item['id']+'/content'
        response = self.client.get(path)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.headers['vary'], 'Cookie')
        self.assertIn('sandbox', response.headers['content-security-policy'])
        self.assertEqual(self.client.get(path, headers={'If-None-Match':response.headers['etag']}).status_code, 304)
        self.assertEqual(member.get(path, headers={'If-None-Match':'*'}).status_code, 404)
        self.assertEqual(TestClient(app).get(path).status_code, 401)
        self.assertEqual(member.get('/api/uploaded-icons').json()['items'], [])
        self.assertEqual(self.bookmark(item['icon'], member).status_code, 404)
        metadata = self.client.get('/api/uploaded-icons').json()['items'][0]
        self.assertNotIn('storage', str(metadata)); self.assertNotIn('data', metadata)

    def test_bookmark_bulk_trash_and_shared_usage_prevent_deletion(self):
        self.setup_owner(); item = self.asset()
        bookmark = self.bookmark(item['icon'])
        self.assertEqual(bookmark.status_code, 200, bookmark.text)
        path = '/api/uploaded-icons/'+item['id']
        self.assertEqual(self.client.get('/api/uploaded-icons').json()['items'][0]['used_by'], 1)
        self.assertEqual(self.client.delete(path, headers=HEADERS).status_code, 409)
        changed = self.client.post('/api/bookmark-tools/bulk', json={'ids':[bookmark.json()['id']], 'action':'icon','icon':'world'}, headers=HEADERS)
        self.assertEqual(changed.status_code, 200, changed.text)
        self.assertTrue(self.client.get('/api/uploaded-icons').json()['items'][0]['in_trash'])
        self.assertEqual(self.client.delete(path, headers=HEADERS).status_code, 409)
        self.assertEqual(self.client.post('/api/trash/'+changed.json()['undo_id']+'/restore', headers=HEADERS).status_code, 200)

    def test_shared_link_permission_controls_icon_preview_and_copied_placement(self):
        self.setup_owner(); item = self.asset(); member = self.member()
        with SessionLocal.begin() as db:
            link = SharedLink(source_name='Custom', name='Shared icon', url='https://shared-icon.test', icon=item['icon'], published=False)
            db.add(link); db.flush(); link_id=link.id
        path = '/api/uploaded-icons/'+item['id']+'/content'
        self.assertEqual(member.get(path).status_code, 404)

        settings = {'name':'Shared icon','icon':item['icon'],'published':True,'access_mode':'all'}
        response = self.client.put('/api/admin/library/'+link_id, json=settings, headers=HEADERS)
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(member.get(path).status_code, 200)
        category = member.get('/api/portal').json()['tabs'][0]['categories'][0]['id']
        self.assertEqual(member.post('/api/library/'+link_id+'/add', json={'category_id':category}, headers=HEADERS).status_code, 200)
        settings['icon']='world'
        self.assertEqual(self.client.put('/api/admin/library/'+link_id, json=settings, headers=HEADERS).status_code, 200)
        self.assertEqual(member.get(path).status_code, 200)
        settings['published']=False
        self.client.put('/api/admin/library/'+link_id, json=settings, headers=HEADERS)
        self.assertEqual(member.get(path).status_code, 404)

    def test_bulk_applies_owned_upload_to_multiple_bookmarks_and_can_undo(self):
        self.setup_owner(); item = self.asset()
        first = self.bookmark('world', url='https://first-icon.test').json()
        second = self.bookmark('world', url='https://second-icon.test').json()
        result = self.client.post('/api/bookmark-tools/bulk', json={
            'ids':[first['id'], second['id']], 'action':'icon', 'icon':item['icon'], 'icon_color':'auto'}, headers=HEADERS)
        self.assertEqual(result.status_code, 200, result.text)
        self.assertEqual(self.client.get('/api/uploaded-icons').json()['items'][0]['used_by'], 2)
        self.assertEqual(self.client.post('/api/trash/'+result.json()['undo_id']+'/restore', headers=HEADERS).status_code, 200)
        for identifier in (first['id'], second['id']):
            self.assertEqual(self.client.get('/api/bookmarks/'+identifier).json()['icon'], 'world')

    def test_encrypted_backup_roundtrip_copies_icon_to_new_owner_and_rewrites_reference(self):
        self.setup_owner(); item=self.asset(); self.bookmark(item['icon'])
        member=self.member()
        exported=self.client.post('/api/backups/export', json={'encrypted':True,'password':'a-backup-password'}, headers=HEADERS)
        self.assertEqual(exported.status_code, 200, exported.text)
        preview=member.post('/api/backups/import-preview', json={'document':exported.json(),'password':'a-backup-password'}, headers=HEADERS)
        self.assertEqual(preview.status_code, 200, preview.text); self.assertEqual(preview.json()['icons'],1)
        result=member.post('/api/backups/import', json={'preview_id':preview.json()['preview_id']}, headers=HEADERS)
        self.assertEqual(result.status_code, 200, result.text)
        own=member.get('/api/uploaded-icons').json()['items'][0]
        self.assertNotEqual(own['icon'],item['icon'])
        bookmark=next(link for tab in member.get('/api/portal').json()['tabs'] for cat in tab['categories'] for link in cat['links'] if link['url']=='https://uploaded.test/')
        self.assertEqual(bookmark['icon'],own['icon'])
        self.assertEqual(member.get('/api/uploaded-icons/'+own['id']+'/content').status_code,200)

    def test_backup_without_images_falls_back_to_builtin_and_missing_asset_is_rejected(self):
        self.setup_owner(); item=self.asset(); self.bookmark(item['icon'])
        plain=self.client.post('/api/backups/export', json={}, headers=HEADERS).json()
        self.assertEqual(len(plain['icons']),1)
        missing={**plain,'icons':[]}
        self.assertEqual(self.client.post('/api/backups/import-preview',json={'document':missing},headers=HEADERS).status_code,422)
        damaged={**plain,'icons':[{**plain['icons'][0], 'data':base64.b64encode(b'not a PNG').decode()}]}
        self.assertEqual(self.client.post('/api/backups/import-preview',json={'document':damaged},headers=HEADERS).status_code,422)
        omitted=self.client.post('/api/backups/export', json={'include_images':False}, headers=HEADERS).json()
        self.assertEqual(omitted['icons'],[])
        self.assertNotIn(item['icon'], str(omitted))
        self.assertEqual(self.client.post('/api/backups/import-preview',json={'document':omitted},headers=HEADERS).status_code,200)

    def test_bad_files_limits_rate_and_single_upload_slot(self):
        self.setup_owner()
        self.assertEqual(self.upload(b'<html>not an icon</html>').status_code,422)
        self.assertEqual(self.upload(b'<!DOCTYPE svg [<!ENTITY x SYSTEM "file:///etc/passwd">]><svg xmlns="http://www.w3.org/2000/svg">&x;</svg>').status_code,422)
        self.assertEqual(self.upload(b'x'*(uploaded_icons.MAX_INPUT+1)).status_code,413)
        upload_slot.acquire()
        try:self.assertEqual(self.upload().status_code,503)
        finally:upload_slot.release()
        item=self.asset()
        self.assertEqual(self.upload().json()['id'],item['id'])
        self.assertEqual(self.client.delete('/api/uploaded-icons/'+item['id']).status_code,403)
        self.assertEqual(self.client.delete('/api/uploaded-icons/'+item['id'],headers=HEADERS).status_code,200)
        with patch.object(uploaded_icons,'MAX_FILES',0):self.assertEqual(self.upload().status_code,409)
        while True:
            result=self.upload()
            if result.status_code==429:break
            self.assertEqual(result.status_code,200,result.text)
        self.assertEqual(result.status_code,429)

    def test_svg_external_images_and_css_cannot_make_network_requests(self):
        self.setup_owner(); hits=[]
        class Handler(BaseHTTPRequestHandler):
            def do_GET(self):
                hits.append(self.path);self.send_response(200);self.end_headers();self.wfile.write(b'body{}')
            def log_message(self,*args):pass
        server=HTTPServer(('127.0.0.1',0),Handler);thread=Thread(target=server.serve_forever,daemon=True);thread.start()
        try:
            for body in (f'<image href="http://127.0.0.1:{server.server_port}/icon.png" width="24" height="24"/>',f'<style>@import url(http://127.0.0.1:{server.server_port}/style.css);</style><rect width="24" height="24"/>'):
                svg=f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24">{body}</svg>'.encode()
                response=self.upload(svg,name='external.svg')
                self.assertIn(response.status_code,(200,422),response.text)
            self.assertEqual(hits,[])
        finally:server.shutdown();server.server_close();thread.join()

    def test_s3_storage_and_cleanup_guard_protect_live_uploaded_icon(self):
        self.setup_owner();fake=FakeS3()
        with patch.dict(os.environ, {'MEDIA_STORAGE_BACKEND':'s3','S3_ENDPOINT_URL':'http://storage.invalid','S3_REGION':'garage','S3_BUCKET':'icons-test','S3_ACCESS_KEY_ID':'test','S3_SECRET_ACCESS_KEY':'test'}),patch.object(storage,'client',return_value=fake):
            item=self.asset()
            with SessionLocal() as db:
                row=db.get(UploadedIcon,item['id']);self.assertIsNone(row.data);self.assertIn('/icons/',row.storage_key)
                bucket, key = row.storage_bucket, row.storage_key
            with SessionLocal.begin() as db:
                db.add(MediaObjectDeletion(bucket=bucket, object_key=key))
            storage.cleanup()
            self.assertEqual(len(fake.objects),1)
            self.assertEqual(self.client.get('/api/uploaded-icons/'+item['id']+'/content').status_code,200)
            self.assertEqual(self.client.delete('/api/uploaded-icons/'+item['id'],headers=HEADERS).status_code,200)
            storage.cleanup();self.assertEqual(fake.objects,{})
