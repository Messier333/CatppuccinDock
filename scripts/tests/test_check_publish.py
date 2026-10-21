"""Exercise publishing safeguards in disposable repositories, never the live index."""
from contextlib import redirect_stdout
import importlib.util
import io
from pathlib import Path
import secrets
import subprocess
import tarfile
import tempfile
import unittest
from unittest.mock import patch

SOURCE = Path(__file__).resolve().parents[2]
spec = importlib.util.spec_from_file_location('check_publish', SOURCE/'scripts/check_publish.py')
publish = importlib.util.module_from_spec(spec)
spec.loader.exec_module(publish)


class PublishingTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory(prefix='dock-publish-test-')
        self.addCleanup(self.directory.cleanup)
        self.root = Path(self.directory.name)
        for name in publish.REQUIRED_FILES:
            target = self.root/name
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes((SOURCE/name).read_bytes())
        self.value = secrets.token_hex(24)
        (self.root/'.env').write_text('AUTH_ENCRYPTION_KEY='+self.value+'\n')
        self.root_patch = patch.object(publish, 'ROOT', self.root)
        self.root_patch.start()
        self.addCleanup(self.root_patch.stop)

    def check(self, *arguments):
        output = io.StringIO()
        with redirect_stdout(output):
            code = publish.main(list(arguments))
        self.assertNotIn(self.value, output.getvalue())
        return code, output.getvalue()

    def test_archive_has_only_checked_source_and_no_host_metadata(self):
        for name in ['logs/auth/auth.log.1', 'garage_data/block.bin', 'exports/bookmarks.json']:
            target = self.root/name
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(self.value)
        target = self.root/'.local-backups/source.tar.gz'
        self.assertEqual(self.check('--archive', str(target))[0], 0)
        with tarfile.open(target) as archive:
            names = archive.getnames()
            self.assertIn('CatppuccinDock/.env.example', names)
            self.assertIn('CatppuccinDock/frontend/package-lock.json', names)
            for entry in archive.getmembers():
                self.assertTrue(entry.isfile())
                self.assertEqual((entry.uid, entry.gid, entry.mtime), (0, 0, 0))
                self.assertNotIn(self.value.encode(), archive.extractfile(entry).read())
            self.assertNotIn('CatppuccinDock/.env', names)
            self.assertFalse(any('/logs/' in name or '/garage_data/' in name or '/exports/' in name for name in names))

    def test_copied_local_secret_blocks_archive_without_printing_value(self):
        (self.root/'README.md').write_text(self.value)
        target = self.root/'.local-backups/source.tar.gz'
        code, output = self.check('--archive', str(target))
        self.assertEqual(code, 1)
        self.assertIn('contains local environment value', output)
        self.assertFalse(target.exists())

    def test_token_blocks_export_and_is_redacted(self):
        token = 'gh'+'p_'+secrets.token_hex(24)
        (self.root/'README.md').write_text(token)
        code, output = self.check()
        self.assertEqual(code, 1)
        self.assertIn('GitHub token detected', output)
        self.assertNotIn(token, output)

    def test_already_tracked_environment_is_rejected(self):
        subprocess.run(['git', 'init', '--quiet', str(self.root)], check=True, capture_output=True)
        subprocess.run(['git', '-C', str(self.root), 'add', '-f', '.env'], check=True, capture_output=True)
        code, output = self.check()
        self.assertEqual(code, 1)
        self.assertIn('ignored file is already tracked', output)

    def test_broken_and_external_symlinks_are_rejected(self):
        (self.root/'broken.txt').symlink_to(self.root/'missing.txt')
        (self.root/'outside.txt').symlink_to(SOURCE/'README.md')
        code, output = self.check()
        self.assertEqual(code, 1)
        self.assertIn('FAIL broken.txt: review symlink', output)
        self.assertIn('FAIL outside.txt: review symlink', output)

    def test_archive_never_overwrites_existing_file(self):
        target = self.root/'existing.tar.gz'
        target.write_bytes(b'existing-source')
        with redirect_stdout(io.StringIO()), patch('sys.stderr', new=io.StringIO()):
            with self.assertRaises(SystemExit):
                publish.main(['--archive', str(target)])
        self.assertEqual(target.read_bytes(), b'existing-source')


if __name__ == '__main__':
    unittest.main()
