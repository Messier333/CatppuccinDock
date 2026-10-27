"""Verify automatic patch versions and safe retries against Git repositories."""
import importlib.util
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

SCRIPT = Path(__file__).resolve().parents[1]/'next_release_tag.py'
spec = importlib.util.spec_from_file_location('next_release_tag', SCRIPT)
version = importlib.util.module_from_spec(spec)
spec.loader.exec_module(version)


class ReleaseVersionTests(unittest.TestCase):
    def test_first_release(self):
        self.assertEqual(version.next_release_tag([], []), 'v1.0.0')

    def test_numeric_order_and_patch_increment(self):
        self.assertEqual(version.next_release_tag(['v1.0.9', 'v1.0.10', 'v0.9.99'], []), 'v1.0.11')

    def test_major_and_minor_versions_are_preserved(self):
        self.assertEqual(version.next_release_tag(['v1.9.99', 'v2.0.0', 'v1.10.0'], []), 'v2.0.1')

    def test_only_stable_canonical_tags_set_the_next_version(self):
        self.assertEqual(version.next_release_tag([
            'v1.2.3', 'v9.0.0-rc.1', 'v9.0.0+build.1', 'v01.0.0',
            '1.0.0', 'v9.0', 'nightly', 'v9.0.0\n', 'v9\u0661.0.0',
        ], []), 'v1.2.4')

    def test_prereleases_alone_do_not_change_initial_version(self):
        self.assertEqual(version.next_release_tag(['v1.0.0-rc.1'], []), 'v1.0.0')

    def test_retry_reuses_highest_stable_tag_on_current_commit(self):
        tags = ['v1.0.4', 'v1.0.5', 'v2.0.0']
        self.assertEqual(version.next_release_tag(tags, ['v1.0.4', 'v1.0.5']), 'v1.0.5')

    def test_prerelease_on_current_commit_does_not_prevent_stable_release(self):
        self.assertEqual(version.next_release_tag(['v1.0.4', 'v1.0.5-rc.1'], ['v1.0.5-rc.1']), 'v1.0.5')


class GitReleaseVersionTests(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory(prefix='dock-version-test-')
        self.addCleanup(directory.cleanup)
        self.root = Path(directory.name)
        self.git('init', '--quiet')
        self.git('config', 'user.name', 'Release test')
        self.git('config', 'user.email', 'release@example.invalid')
        self.commit()

    def git(self, *arguments):
        return subprocess.run(
            ['git', *arguments], cwd=self.root, check=True, capture_output=True, text=True,
        ).stdout.strip()

    def commit(self):
        self.git('-c', 'commit.gpgsign=false', 'commit', '--quiet', '--allow-empty', '-m', 'Test commit')

    def selected_tag(self):
        return subprocess.run(
            [sys.executable, str(SCRIPT)], cwd=self.root, check=True, capture_output=True, text=True,
        ).stdout.strip()

    def test_lightweight_tag_is_reused_then_incremented_after_merge(self):
        self.git('tag', 'v1.0.5')
        self.assertEqual(self.selected_tag(), 'v1.0.5')
        self.commit()
        self.assertEqual(self.selected_tag(), 'v1.0.6')
        self.assertEqual(self.git('tag', '--list'), 'v1.0.5')

    def test_annotated_tag_is_reused_on_rerun(self):
        self.git('-c', 'tag.gpgsign=false', 'tag', '-a', 'v1.0.6', '-m', 'Release v1.0.6')
        self.assertEqual(self.selected_tag(), 'v1.0.6')

    def test_existing_versions_on_other_branches_are_not_reallocated(self):
        original = self.git('rev-parse', 'HEAD')
        self.git('checkout', '--quiet', '-b', 'other-release')
        self.commit()
        self.git('tag', 'v1.0.10')
        self.git('checkout', '--quiet', '--detach', original)
        self.assertEqual(self.selected_tag(), 'v1.0.11')

    def test_git_errors_fail_without_outputting_a_release_version(self):
        self.git('init', '--quiet', 'empty')
        result = subprocess.run(
            [sys.executable, str(SCRIPT)], cwd=self.root/'empty', capture_output=True, text=True,
        )
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(result.stdout, '')


if __name__ == '__main__':
    unittest.main()
