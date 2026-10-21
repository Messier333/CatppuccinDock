import base64
from io import BytesIO
import os
import unittest
from unittest.mock import patch

from botocore.exceptions import EndpointConnectionError
from fastapi import HTTPException
from fastapi.testclient import TestClient
from sqlalchemy import func, select

import test_auth as legacy
from test_auth import HEADERS
from test_backgrounds import gif
from app.db.models import BackgroundImage, MediaObjectDeletion
from app.db.session import SessionLocal
from app.main import app
from app.services import backups
from app.services.media import storage
from app.services.media.migrate_storage import migrate


class FakeS3:
    def __init__(self):
        self.objects = {}
        self.gets = 0
        self.offline = False
        self.corrupt = False

    def check(self):
        if self.offline:
            raise EndpointConnectionError(endpoint_url='http://private-storage.invalid')

    def head_bucket(self, **kwargs):
        self.check()

    def put_object(self, *, Bucket, Key, Body, **kwargs):
        self.check()
        self.objects[Bucket, Key] = Body

    def get_object(self, *, Bucket, Key):
        self.check()
        self.gets += 1
        return {'Body': BytesIO(b'corrupt' if self.corrupt else self.objects[Bucket, Key])}

    def delete_object(self, *, Bucket, Key):
        self.check()
        self.objects.pop((Bucket, Key), None)


class MediaStorageTests(unittest.TestCase):
    setup_owner = legacy.AuthenticationTests.setup_owner

    def setUp(self):
        self.s3 = FakeS3()
        self.addCleanup(patch.stopall)
        patch.dict(os.environ, {'MEDIA_STORAGE_BACKEND':'s3', 'S3_ENDPOINT_URL':'http://storage.invalid:3900',
            'S3_REGION':'garage', 'S3_BUCKET':'test-bucket', 'S3_ACCESS_KEY_ID':'test-key', 'S3_SECRET_ACCESS_KEY':'test-secret'}).start()
        patch.object(storage, 'client', return_value=self.s3).start()
        legacy.AuthenticationTests.setUp(self)
        self.setup_owner()

    tearDown = legacy.AuthenticationTests.tearDown

    def upload(self):
        return self.client.post('/api/backgrounds', content=gif(), headers=HEADERS | {'Content-Type':'image/gif'})

    def test_private_s3_roundtrip_metadata_dedup_and_304_without_object_fetch(self):
        response = self.upload()
        self.assertEqual(response.status_code, 200, response.text)
        image = response.json()
        with SessionLocal() as db:
            row = db.get(BackgroundImage, image['id'])
            self.assertIsNone(row.data)
            self.assertEqual(row.storage_bucket, 'test-bucket')
            self.assertTrue(row.storage_key.startswith('catppuccindock/backgrounds/1/'))
        self.assertNotIn('storage_key', str(image))
        self.assertEqual(self.client.get('/api/backgrounds').json()['items'], [image])
        self.assertEqual(self.s3.gets, 0)
        path = '/api/backgrounds/' + image['id'] + '/content'
        body = self.client.get(path)
        self.assertEqual(body.content, gif())
        self.assertEqual(self.client.get(path, headers={'If-None-Match':body.headers['etag']}).status_code, 304)
        self.assertEqual(self.s3.gets, 1)
        self.assertEqual(TestClient(app).get(path).status_code, 401)
        self.assertEqual(self.upload().json()['id'], image['id'])
        self.assertEqual(len(self.s3.objects), 1)

    def test_s3_failure_never_silently_writes_bytes_to_database(self):
        self.s3.offline = True
        response = self.upload()
        self.assertEqual(response.status_code, 503, response.text)
        self.assertNotIn('private-storage', response.text)
        with SessionLocal() as db:
            self.assertEqual(db.scalar(select(func.count()).select_from(BackgroundImage)), 0)
        self.assertEqual(self.client.get('/api/health').status_code, 503)

    def test_legacy_migration_dry_run_verified_resume_preserves_id_and_source(self):
        with patch.dict(os.environ, {'MEDIA_STORAGE_BACKEND':'database'}):
            image = self.upload().json()
        self.assertEqual(migrate(), 1)
        self.assertEqual(self.s3.objects, {})
        self.assertEqual(migrate(apply=True), 1)
        self.assertEqual(migrate(apply=True), 0)
        with SessionLocal() as db:
            row = db.get(BackgroundImage, image['id'])
            self.assertIsNone(row.data)
            self.assertEqual(storage.read(row), gif())
        self.assertEqual(self.client.get('/api/backgrounds').json()['items'], [image])

    def test_corrupt_migration_leaves_legacy_bytes_and_cleans_failed_upload(self):
        with patch.dict(os.environ, {'MEDIA_STORAGE_BACKEND':'database'}):
            image = self.upload().json()
        self.s3.corrupt = True
        with self.assertRaises(HTTPException):
            migrate(apply=True)
        with SessionLocal() as db:
            row = db.get(BackgroundImage, image['id'])
            self.assertEqual(row.data, gif())
            self.assertIsNone(row.storage_key)
        storage.cleanup()
        self.assertEqual(self.s3.objects, {})

    def test_transactional_delete_retries_outage_and_preserves_referenced_files(self):
        image = self.upload().json()
        with SessionLocal() as db:
            row = db.get(BackgroundImage, image['id'])
            bucket, key = row.storage_bucket, row.storage_key
        with SessionLocal.begin() as db:
            db.add(MediaObjectDeletion(bucket=bucket, object_key=key))
        storage.cleanup()
        self.assertEqual(len(self.s3.objects), 1)
        self.s3.offline = True
        self.assertEqual(self.client.delete('/api/backgrounds/'+image['id'], headers=HEADERS).status_code, 200)
        storage.cleanup()
        with SessionLocal() as db:
            self.assertGreater(db.scalar(select(func.count()).select_from(MediaObjectDeletion)), 0)
        self.s3.offline = False
        storage.cleanup()
        self.assertEqual(self.s3.objects, {})
        with SessionLocal() as db:
            self.assertEqual(db.scalar(select(func.count()).select_from(MediaObjectDeletion)), 0)

    def test_encrypted_backup_embeds_s3_bytes_and_imports_into_other_users_namespace(self):
        image = self.upload().json()
        exported = self.client.post('/api/backups/export', json={'encrypted':True,'password':'a-backup-password'}, headers=HEADERS)
        self.assertEqual(exported.status_code, 200, exported.text)
        document = backups.open_document(exported.json(), 'a-backup-password')
        self.assertEqual(base64.b64decode(document['images'][0]['data']), gif())
        self.assertNotIn('storage_key', str(document))
        self.client.post('/api/admin/users', json={'username':'storage-member','password':'a-member-password'}, headers=HEADERS)
        member = TestClient(app)
        member.post('/api/auth/login', json={'username':'storage-member','password':'a-member-password'}, headers=HEADERS)
        self.assertEqual(member.get('/api/backgrounds/'+image['id']+'/content').status_code, 404)
        preview = member.post('/api/backups/import-preview', json={'document':exported.json(),'password':'a-backup-password'}, headers=HEADERS)
        self.assertEqual(preview.status_code, 200, preview.text)
        restored = member.post('/api/backups/import', json={'preview_id':preview.json()['preview_id']}, headers=HEADERS)
        self.assertEqual(restored.status_code, 200, restored.text)
        own = member.get('/api/backgrounds').json()['items'][0]
        self.assertNotEqual(own['id'], image['id'])
        self.assertEqual(member.get('/api/backgrounds/'+own['id']+'/content').content, gif())
        self.assertEqual(len(self.s3.objects), 2)

    def test_storage_configuration_uses_explicit_credentials_and_path_addressing(self):
        storage._client.cache_clear()
        with patch.object(storage.boto3, 'client') as make:
            storage._client(*storage.configuration())
            config = make.call_args.kwargs['config']
            self.assertEqual(config.s3['addressing_style'], 'path')
            self.assertEqual(config.request_checksum_calculation, 'when_required')
            self.assertEqual(make.call_args.kwargs['aws_access_key_id'], 'test-key')
        storage._client.cache_clear()

    def test_verified_provider_cache_copies_s3_file_without_another_download(self):
        source = {'provider':'commons','item_id':'42','title':'Forest','author':'Artist',
            'page_url':'https://commons.wikimedia.org/?curid=42','license':'CC BY 4.0',
            'license_url':'https://creativecommons.org/licenses/by/4.0/'}
        payload = {'provider':'commons','item_id':'42'}
        with patch('app.services.media.gif_search.download', return_value=(gif(), 'Forest', source)) as download:
            original = self.client.post('/api/backgrounds/import', json=payload, headers=HEADERS)
            self.assertEqual(original.status_code, 200, original.text)
            self.client.post('/api/admin/users', json={'username':'cache-member','password':'a-member-password'}, headers=HEADERS)
            member = TestClient(app)
            member.post('/api/auth/login', json={'username':'cache-member','password':'a-member-password'}, headers=HEADERS)
            copied = member.post('/api/backgrounds/import', json=payload, headers=HEADERS)
            self.assertEqual(copied.status_code, 200, copied.text)
            self.assertEqual(download.call_count, 1)
        self.assertEqual(len(self.s3.objects), 2)
        self.assertNotEqual(copied.json()['id'], original.json()['id'])
        self.assertEqual(copied.json()['source'], source)
        self.assertEqual(member.get('/api/backgrounds/'+copied.json()['id']+'/content').content, gif())
