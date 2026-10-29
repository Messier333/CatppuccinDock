"""Exercise release ancestry, exact artifact identities and disposable image checks."""
from contextlib import redirect_stderr, redirect_stdout
import io
import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch

from scripts import check_release_tag, release_images, smoke_release


class ReleaseTagTests(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory(prefix='dock-release-tag-test-')
        self.addCleanup(directory.cleanup)
        previous = Path.cwd()
        os.chdir(directory.name)
        self.addCleanup(os.chdir, previous)
        self.git('init', '--quiet', '--initial-branch=main')
        self.git('config', 'user.name', 'Release test')
        self.git('config', 'user.email', 'release@example.invalid')
        self.commit = self.new_commit()
        self.git('update-ref', 'refs/remotes/origin/main', self.commit)

    def git(self, *arguments):
        return subprocess.run(['git', *arguments], check=True, capture_output=True, text=True).stdout.strip()

    def new_commit(self):
        self.git('-c', 'commit.gpgsign=false', 'commit', '--quiet', '--allow-empty', '-m', 'Test commit')
        return self.git('rev-parse', 'HEAD')

    def test_lightweight_tag_on_main_is_accepted(self):
        self.git('tag', 'v1.2.3')
        check_release_tag.validate('v1.2.3', self.commit)

    def test_annotated_prerelease_on_main_is_accepted(self):
        self.git('-c', 'tag.gpgsign=false', 'tag', '-a', 'v1.2.3-rc.1+build.4', '-m', 'Release test')
        check_release_tag.validate('v1.2.3-rc.1+build.4', self.commit)

    def test_old_commit_in_main_can_be_released(self):
        self.git('tag', 'v1.2.3')
        self.git('update-ref', 'refs/remotes/origin/main', self.new_commit())
        self.git('checkout', '--quiet', '--detach', self.commit)
        check_release_tag.validate('v1.2.3', self.commit)

    def test_unmerged_feature_commit_is_rejected(self):
        self.git('checkout', '--quiet', '-b', 'feature/unmerged')
        feature = self.new_commit()
        self.git('tag', 'v1.2.3')
        with self.assertRaisesRegex(ValueError, 'not in origin/main'):
            check_release_tag.validate('v1.2.3', feature)

    def test_tag_and_checked_out_commit_must_match_event(self):
        self.git('tag', 'v1.2.3')
        newer = self.new_commit()
        with self.assertRaisesRegex(ValueError, 'must match'):
            check_release_tag.validate('v1.2.3', newer)
        with self.assertRaisesRegex(ValueError, 'must match'):
            check_release_tag.validate('v1.2.3', self.commit)

    def test_missing_main_history_fails_closed(self):
        self.git('tag', 'v1.2.3')
        self.git('update-ref', '-d', 'refs/remotes/origin/main')
        with self.assertRaises(subprocess.CalledProcessError):
            check_release_tag.validate('v1.2.3', self.commit)

    def test_invalid_versions_are_rejected_before_git_lookup(self):
        for tag in ('v01.2.3', 'v1.2', 'v1.2.3-01', 'v1.2.3-..', 'v1.2.3+bad..metadata',
                    'v1.2.3/unsafe', 'v1.2.3\n', 'v1.2.3-'+'x'*128):
            with self.subTest(tag=tag), self.assertRaisesRegex(ValueError, 'SemVer'):
                check_release_tag.validate(tag, self.commit)


class ReleaseImageTests(unittest.TestCase):
    repository = 'Example/Portal'
    commit = 'a'*40

    def setUp(self):
        directory = tempfile.TemporaryDirectory(prefix='dock-release-images-test-')
        self.addCleanup(directory.cleanup)
        self.root = Path(directory.name)
        for component, digest in (('frontend', 'b'*64), ('backend', 'c'*64)):
            release_images.record_image(self.root/f'release-image-{component}', self.repository,
                                        self.commit, component, f'ghcr.io/example/portal-{component}', 'sha256:'+digest)

    def test_images_are_pinned_to_published_digests(self):
        images = release_images.load_images(self.root, self.repository, self.commit)
        self.assertEqual(images['frontend'], 'ghcr.io/example/portal-frontend@sha256:'+'b'*64)
        self.assertEqual(images['backend'], 'ghcr.io/example/portal-backend@sha256:'+'c'*64)

    def rewrite(self, **updates):
        path = self.root/'release-image-frontend/frontend.json'
        record = json.loads(path.read_text())
        record.update(updates)
        path.write_text(json.dumps(record))

    def test_artifact_from_another_commit_is_rejected(self):
        with self.assertRaisesRegex(ValueError, 'source commit'):
            release_images.load_images(self.root, self.repository, 'd'*40)

    def test_external_repository_or_wrong_component_is_rejected(self):
        for image in ('ghcr.io/other/project-frontend', 'ghcr.io/example/portal-backend'):
            self.rewrite(image=image)
            with self.assertRaisesRegex(ValueError, 'this repository'):
                release_images.load_images(self.root, self.repository, self.commit)

    def test_mutable_tags_and_malformed_digests_are_rejected(self):
        for digest in ('latest', 'sha256:abc', None, 'sha256:'+'F'*64):
            self.rewrite(digest=digest)
            with self.assertRaisesRegex(ValueError, 'SHA256'):
                release_images.load_images(self.root, self.repository, self.commit)

    def test_missing_image_is_rejected(self):
        (self.root/'release-image-backend/backend.json').unlink()
        with self.assertRaisesRegex(ValueError, 'Both frontend and backend'):
            release_images.load_images(self.root, self.repository, self.commit)

    def test_duplicate_artifact_is_rejected(self):
        source = self.root/'release-image-frontend/frontend.json'
        (self.root/'duplicate.json').write_bytes(source.read_bytes())
        with self.assertRaisesRegex(ValueError, 'Duplicate'):
            release_images.load_images(self.root, self.repository, self.commit)

    def test_invalid_record_is_rejected(self):
        (self.root/'release-image-frontend/frontend.json').write_text('[]')
        with self.assertRaisesRegex(ValueError, 'record'):
            release_images.load_images(self.root, self.repository, self.commit)


class PublishedImageSmokeTests(unittest.TestCase):
    images = {'frontend': 'frontend@sha256:'+'a'*64, 'backend': 'backend@sha256:'+'b'*64}

    def execute(self, fail_start=False, fail_cleanup=False, port='127.0.0.1:18091\n', http_error=False):
        self.commands = []

        def run(command, **options):
            self.commands.append((command, options))
            if 'up' in command and fail_start:
                raise subprocess.CalledProcessError(1, command)
            code = 1 if 'down' in command and fail_cleanup else 0
            if command[:2] == ['docker', 'inspect']:
                service = command[-1].removesuffix('-id')
                memberships = {
                    'frontend': {'project_app': {}},
                    'backend': {'project_app': {}, 'project_data': {}},
                    'database': {'project_data': {}},
                    'garage': {'project_data': {}},
                }
                isolation = [{'HostConfig': {
                    'ReadonlyRootfs': True, 'CapDrop': ['ALL'],
                    'SecurityOpt': ['no-new-privileges:true'],
                    'PidsLimit': 128, 'Tmpfs': {'/tmp': 'size=128m'},
                }, 'NetworkSettings': {'Networks': memberships[service]}}]
                return subprocess.CompletedProcess(command, code, stdout=json.dumps(isolation))
            if command[:3] == ['docker', 'network', 'inspect']:
                return subprocess.CompletedProcess(command, code, stdout=json.dumps([{'Internal': True}]))
            if 'ps' in command and '-q' in command:
                return subprocess.CompletedProcess(command, code, stdout=command[-1]+'-id\n')
            return subprocess.CompletedProcess(command, code, stdout=port if 'port' in command else '')

        with patch.object(smoke_release.subprocess, 'run', side_effect=run), \
                patch.object(smoke_release, 'check_http', side_effect=RuntimeError('unhealthy') if http_error else None) as http, \
                patch.object(smoke_release.time, 'sleep'), \
                redirect_stdout(io.StringIO()), redirect_stderr(io.StringIO()):
            status = smoke_release.run_stack(self.images, 'linux/amd64')
            return status, http

    def test_published_images_are_used_without_builds_or_host_credentials(self):
        with patch.dict(os.environ, {'POSTGRES_PASSWORD': 'host-password', 'ADMIN_SETUP_CODE': 'host-setup-code'}):
            status, http = self.execute()
        self.assertEqual(status, 0)
        http.assert_called_once_with('http://127.0.0.1:18091')
        command, options = next(item for item in self.commands if 'up' in item[0])
        self.assertIn('--no-build', command)
        self.assertEqual(command[command.index('--pull')+1], 'never')
        self.assertEqual(command[command.index('--env-file')+1], '/dev/null')
        self.assertTrue(command[command.index('-p')+1].startswith('catppuccindock-release-'))
        self.assertEqual(options['env']['SMOKE_FRONTEND_IMAGE'], self.images['frontend'])
        self.assertEqual(options['env']['PORTAL_PORT'], '127.0.0.1:0')
        self.assertNotEqual(options['env']['POSTGRES_PASSWORD'], 'host-password')
        self.assertNotEqual(options['env']['ADMIN_SETUP_CODE'], 'host-setup-code')
        self.assertFalse(Path(options['cwd']).exists())
        self.assertEqual(self.commands[-1][0][-3:], ['down', '--volumes', '--remove-orphans'])
        self.assertFalse(any('logs' in command for command, _ in self.commands))
        self.assertEqual(sum('exec' in command for command, _ in self.commands), 2)
        self.assertEqual(sum(command[:2] == ['docker', 'inspect'] for command, _ in self.commands), 4)
        self.assertEqual(sum(command[:3] == ['docker', 'network', 'inspect'] for command, _ in self.commands), 1)

    def test_start_failure_still_removes_only_the_disposable_project(self):
        status, http = self.execute(fail_start=True)
        self.assertEqual(status, 1)
        http.assert_not_called()
        self.assertIn('down', self.commands[-1][0])
        self.assertEqual(len({command[command.index('-p')+1] for command, _ in self.commands}), 1)

    def test_cleanup_failure_fails_the_job(self):
        self.assertEqual(self.execute(fail_cleanup=True)[0], 1)

    def test_unhealthy_http_fails_and_cleans_up(self):
        self.assertEqual(self.execute(http_error=True)[0], 1)
        self.assertIn('down', self.commands[-1][0])

    def test_unexpected_public_bind_is_rejected(self):
        status, http = self.execute(port='0.0.0.0:18091\n')
        self.assertEqual(status, 1)
        http.assert_not_called()

    def test_health_check_requires_frontend_html_and_database_and_storage(self):
        def response(body):
            result = io.BytesIO(body)
            result.status = 200
            return result

        for health in ({'status': 'ok', 'database': 'ok', 'storage': 's3'},
                       {'status': 'ok', 'database': 'ok', 'storage': 'local'}):
            responses = [response(b'<html>app</html>'), response(json.dumps(health).encode())]
            with patch.object(smoke_release, 'urlopen', side_effect=responses):
                if health['storage'] == 's3':
                    smoke_release.check_http('http://127.0.0.1:18091')
                else:
                    with self.assertRaisesRegex(RuntimeError, 'not healthy'):
                        smoke_release.check_http('http://127.0.0.1:18091')


if __name__ == '__main__':
    unittest.main()
