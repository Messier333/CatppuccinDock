"""Verify deployment assets exclude runtime data and install a pinned version."""
import hashlib
import importlib.util
from pathlib import Path
import secrets
import tarfile
import tempfile
import unittest
from unittest.mock import patch

SOURCE = Path(__file__).resolve().parents[2]
spec = importlib.util.spec_from_file_location('prepare_release', SOURCE/'scripts/prepare_release.py')
release = importlib.util.module_from_spec(spec)
spec.loader.exec_module(release)


class ReleaseAssetsTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory(prefix='dock-release-test-')
        self.addCleanup(self.directory.cleanup)
        self.root = Path(self.directory.name)/'source'
        self.output = Path(self.directory.name)/'assets'
        for name in [*release.BUNDLE_FILES, '.github/release-notes.md']:
            target = self.root/name
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes((SOURCE/name).read_bytes())
        self.root_patch = patch.object(release, 'ROOT', self.root)
        self.root_patch.start()
        self.addCleanup(self.root_patch.stop)

    def test_bundle_omits_local_secrets_and_contains_complete_install_files(self):
        secret = secrets.token_hex(24)
        for name in ['.env', 'logs/auth/auth.log', 'private.db', 'uploads/image.png']:
            target = self.root/name
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(secret)
        release.prepare('v1.2.3', 'Example/Portal', self.output)
        with tarfile.open(self.output/'CatppuccinDock-v1.2.3-deploy.tar.gz') as archive:
            names = set(archive.getnames())
            self.assertFalse(names & {'.env', 'logs/auth/auth.log', 'private.db', 'uploads/image.png'})
            for name in ['docker-compose.yml', '.env.example', 'DEPLOY.md']:
                self.assertIn(name, names)
            for entry in archive.getmembers():
                self.assertTrue(entry.isfile())
                self.assertNotIn(secret.encode(), archive.extractfile(entry).read())
            environment = archive.extractfile('.env.example').read().decode()
            self.assertIn('IMAGE_TAG=1.2.3\n', environment)
            self.assertIn('GHCR_IMAGE_PREFIX=ghcr.io/example/portal\n', environment)
            self.assertIn('POSTGRES_PASSWORD=\n', environment)
            self.assertIn('AUTH_ENCRYPTION_KEY=\n', environment)
        notes = (self.output/'release-notes.md').read_text()
        self.assertNotIn('@@', notes)
        self.assertIn('ghcr.io/example/portal-frontend:1.2.3', notes)
        self.assertIn('ghcr.io/example/portal-backend:1.2.3', notes)
        self.assertIn('/Example/Portal/releases/download/v1.2.3/', notes)
        self.assertIn('docker compose up -d', notes)
        self.assertIn('infisical sm run', notes)
        self.assertIn('docker compose --env-file /dev/null up -d', notes)
        self.assertNotIn('init-env.sh', notes)
        self.assertEqual(set(path.name for path in self.output.iterdir()), {
            'release-notes.md', 'docker-compose.yml', '.env.example',
            'CatppuccinDock-v1.2.3-deploy.tar.gz', 'SHA256SUMS',
        })

    def test_downloaded_files_match_checksums(self):
        attachments = release.prepare('v1.0.0', 'Example/Portal', self.output)
        lines = (self.output/'SHA256SUMS').read_text().splitlines()
        self.assertEqual(len(lines), len(attachments)-1)
        for line in lines:
            digest, name = line.split('  ', 1)
            self.assertIn(name, attachments)
            self.assertEqual(digest, hashlib.sha256((self.output/name).read_bytes()).hexdigest())

    def test_nonempty_example_credentials_are_rejected_before_writing_assets(self):
        path = self.root/'.env.example'
        path.write_text(path.read_text().replace('POSTGRES_PASSWORD=\n', 'POSTGRES_PASSWORD='+secrets.token_hex(24)+'\n'))
        with self.assertRaisesRegex(ValueError, 'blank credentials'):
            release.prepare('v1.0.0', 'Example/Portal', self.output)
        self.assertFalse(self.output.exists())

    def test_unsafe_tags_and_repository_names_are_rejected(self):
        for tag, repository in [('v1.0.0/../../secret', 'Example/Portal'), ('main', 'Example/Portal'), ('v1.0.0', '../Portal'), ('v1.0.0', 'Example/Portal/extra')]:
            with self.subTest(tag=tag, repository=repository), self.assertRaises(ValueError):
                release.prepare(tag, repository, self.output)
        self.assertFalse(self.output.exists())

    def test_existing_asset_directory_is_not_overwritten(self):
        self.output.mkdir()
        marker = self.output/'existing.txt'
        marker.write_text('preserved')
        with self.assertRaises(FileExistsError):
            release.prepare('v1.0.0', 'Example/Portal', self.output)
        self.assertEqual(marker.read_text(), 'preserved')

    def test_prerelease_build_metadata_does_not_make_an_invalid_image_tag(self):
        release.prepare('v1.1.0-rc.1+build.2', 'Example/Portal', self.output)
        environment = (self.output/'.env.example').read_text()
        self.assertIn('IMAGE_TAG=1.1.0-rc.1\n', environment)


if __name__ == '__main__':
    unittest.main()
