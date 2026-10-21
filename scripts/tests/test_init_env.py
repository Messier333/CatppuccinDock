"""Check first-install credentials and safe reruns without touching the live .env."""
import base64
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[2]
KEYS = ('POSTGRES_PASSWORD', 'ADMIN_SETUP_CODE', 'AUTH_ENCRYPTION_KEY', 'S3_ACCESS_KEY_ID', 'S3_SECRET_ACCESS_KEY', 'GARAGE_RPC_SECRET')


class InitEnvironmentTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory(prefix='dock-init-test-')
        self.addCleanup(self.directory.cleanup)
        self.root = Path(self.directory.name)
        shutil.copy(ROOT/'.env.example', self.root/'.env.example')

    def run_init(self, environment=None):
        return subprocess.run(['sh', str(ROOT/'scripts/init-env.sh')], cwd=self.root, env=environment, capture_output=True, text=True)

    def test_first_install_generates_valid_private_credentials_without_logging_them(self):
        result = self.run_init()
        self.assertEqual(result.returncode, 0, result.stderr)
        target = self.root/'.env'
        values = dict(line.split('=', 1) for line in target.read_text().splitlines() if '=' in line and not line.startswith('#'))
        for key in KEYS:
            self.assertTrue(values[key], key)
            self.assertNotIn(values[key], result.stdout+result.stderr)
        self.assertEqual(len(base64.urlsafe_b64decode(values['AUTH_ENCRYPTION_KEY'])), 32)
        self.assertRegex(values['S3_ACCESS_KEY_ID'], r'^GK[0-9a-f]{32}$')
        self.assertRegex(values['GARAGE_RPC_SECRET'], r'^[0-9a-f]{64}$')
        self.assertEqual(target.stat().st_mode & 0o777, 0o600)
        first = target.read_bytes()
        self.assertEqual(self.run_init().returncode, 0)
        self.assertEqual(target.read_bytes(), first)
        self.assertFalse((self.root/'.env.init.lock').exists())

    def test_fills_blanks_preserves_values_and_never_executes_dotenv(self):
        target = self.root/'.env'
        existing = "# Operator settings\nexport POSTGRES_PASSWORD = 'keep # $special'\nADMIN_SETUP_CODE=$(touch owned)\nAUTH_ENCRYPTION_KEY=\"\" # generate\nS3_ACCESS_KEY_ID=''\nPORTAL_PORT=9190\n"
        target.write_text(existing)
        result = self.run_init()
        self.assertEqual(result.returncode, 0, result.stderr)
        output = target.read_text()
        self.assertIn("export POSTGRES_PASSWORD = 'keep # $special'\n", output)
        self.assertIn('ADMIN_SETUP_CODE=$(touch owned)\n', output)
        self.assertIn('PORTAL_PORT=9190\n', output)
        self.assertRegex(output, r'AUTH_ENCRYPTION_KEY=[A-Za-z0-9_-]{43}=\n')
        self.assertFalse((self.root/'owned').exists())

    def test_failed_random_generator_keeps_existing_file_unchanged(self):
        target = self.root/'.env'
        target.write_text('POSTGRES_PASSWORD=\n# preserve this file\n')
        original = target.read_bytes()
        tools = self.root/'tools';tools.mkdir()
        fake = tools/'openssl';fake.write_text('#!/bin/sh\nexit 42\n');fake.chmod(0o700)
        result = self.run_init({**os.environ, 'PATH':str(tools)+os.pathsep+os.environ['PATH']})
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(target.read_bytes(), original)
        self.assertFalse(list(self.root.glob('.env.init.*')))

    def test_concurrent_run_does_not_remove_another_runs_lock(self):
        lock = self.root/'.env.init.lock';lock.mkdir()
        self.assertNotEqual(self.run_init().returncode, 0)
        self.assertTrue(lock.is_dir())
        self.assertFalse((self.root/'.env').exists())

    def test_existing_symlink_is_not_followed_or_replaced(self):
        original = self.root/'external.env';original.write_text('preserved\n')
        (self.root/'.env').symlink_to(original)
        self.assertNotEqual(self.run_init().returncode, 0)
        self.assertEqual(original.read_text(), 'preserved\n')
        self.assertTrue((self.root/'.env').is_symlink())

    def test_missing_template_does_not_create_partial_environment(self):
        (self.root/'.env.example').unlink()
        self.assertNotEqual(self.run_init().returncode, 0)
        self.assertFalse((self.root/'.env').exists())
        self.assertFalse((self.root/'.env.init.lock').exists())

    def test_explicit_environment_path_is_supported_without_local_dotenv(self):
        target = self.root/'private'/'env'
        result = subprocess.run(['sh',str(ROOT/'scripts/init-env.sh'),'--env-file',str(target)],cwd=self.root,capture_output=True,text=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(target.stat().st_mode & 0o777, 0o600)
        self.assertFalse((self.root/'.env').exists())


if __name__ == '__main__':
    unittest.main()
