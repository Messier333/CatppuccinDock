#!/usr/bin/env python3
"""Inspect Git candidates without printing secret values or changing the index.

Checks filenames, common credential formats and secrets in local .env files.
This is a pre-publish check of current files, not a scan of commit history.
"""
from contextlib import contextmanager
import argparse
import io
from pathlib import Path
import re
import subprocess
import sys
import tarfile
import tempfile

ROOT = Path(__file__).resolve().parents[1]
SECRET_KEY = re.compile(r'PASSWORD|SECRET|TOKEN|PRIVATE_KEY|ENCRYPTION_KEY|SETUP_CODE|ACCESS_KEY_ID', re.I)
MARKERS = {
    'private key': re.compile(rb'-----BEGIN (?:RSA |EC |OPENSSH |DSA |PGP )?PRIVATE KEY(?: BLOCK)?-----'),
    'GitHub token': re.compile(rb'\b(?:gh[pousr]_[A-Za-z0-9]{30,}|github_pat_[A-Za-z0-9_]{40,})\b'),
    'AWS access key': re.compile(rb'\b(?:AKIA|ASIA)[A-Z0-9]{16}\b'),
    'Slack token': re.compile(rb'\bxox[baprs]-[A-Za-z0-9-]{20,}\b'),
    'GitLab token': re.compile(rb'\bglpat-[A-Za-z0-9_-]{20,}\b'),
    'Google API key': re.compile(rb'\bAIza[A-Za-z0-9_-]{35}\b'),
    'database dump': re.compile(rb'(?m)^(?:-- PostgreSQL database dump|-- MySQL dump)(?:\s|$)'),
}
BLOCKED_SUFFIXES = {'.pem', '.key', '.crt', '.cer', '.p12', '.pfx', '.jks', '.keystore', '.db', '.sqlite', '.sqlite3', '.dump', '.har', '.rdb', '.aof'}
EXCLUDED_SAMPLES = (
    '.env', '.env.local', '.env.production', 'frontend/.env.local', 'backend/.env.test',
    '.local-backups/server.dump', '.local-backups/server.env', 'logs/auth/auth.log',
    'frontend/node_modules/example/index.js', 'frontend/dist/index.html',
    'backend/app/__pycache__/main.cpython-312.pyc', 'private.key',
    'credentials.json', 'service-account-prod.json', 'backups/data.sql',
    'deploy/nginx/trusted-proxies/production.conf', 'deploy/fail2ban/production.local',
    'docker-compose.override.yml',
    'production.env', 'backend/production.env.local', '.envrc', '.direnv/cache',
    'database.sql', 'backend/server.sql', 'frontend/debug.har',
    'frontend/test-results/trace.zip', 'frontend/playwright-report/index.html',
    'frontend/playwright/.auth/admin.json', 'frontend/storage-state-admin.json',
    'frontend/src/temporary.vue.orig', 'backend/app/temporary.py.rej',
    'tmp/debug.txt', '.tmp/scratch.json', '.coverage.worker-1',
    'garage_meta/meta.db', 'garage_data/block.bin', 'storage/icons/image.png',
    'exports/bookmarks.json', 'logs/auth/auth.log.1', 'debug.log.gz',
    'database.sql.bz2', 'database.dump.gz', 'database.db.gz', 'database.sqlite3.gz',
    'backup.tar', 'backup.tar.gz', 'backup.tar.zst', 'backup.tgz',
    'backup.zip', 'backup.7z', 'backup.rar',
    'private/session.json', 'server.crt', 'id_ecdsa', '.codex/config.toml',
    '.agents/settings.json', '.claude/settings.json', '.cursor/settings.json',
    'docker-compose.local.yaml', 'compose.production.local.yaml',
    'catppuccindock-2026-01-01.json', 'catppuccindock-encrypted-2026-01-01.json',
    'bookmarks.html',
)
PUBLISHABLE_SAMPLES = (
    '.env.example', 'production.env.example', 'backend/.env.test.example',
    'backend/app/db/migrations/schema.sql',
    'backend/app/services/media/media_policy.py',
    'frontend/src/components/backgrounds/BackgroundPicker.vue',
    'backend/app/services/backups.py', 'backend/app/api/backups.py',
    'deploy/garage/garage.toml', 'docs/api.md',
)
REQUIRED_FILES = (
    '.env.example', '.gitignore', '.dockerignore', '.editorconfig', '.gitattributes', 'docker-compose.yml',
    'frontend/package.json', 'frontend/package-lock.json', 'frontend/.dockerignore',
    'frontend/nginx.conf', 'frontend/nginx-main.conf', 'frontend/security-headers.conf',
    'frontend/CATPPUCCIN-STARTPAGE-LICENSE', 'backend/requirements.txt',
    'backend/.dockerignore', 'deploy/nginx/trusted-proxies/proxy.conf.example',
    'deploy/fail2ban/catppuccindock.local.example',
    'README.md', 'docs/architecture.md', 'docs/usage.md', 'docs/authentication.md',
    'docs/integrations.md', 'docs/development.md', 'docs/api.md', 'docs/storage.md',
    'docs/publishing.md', 'deploy/garage/garage.toml', 'scripts/setup_storage.py',
    '.github/workflows/containers.yml', '.github/workflows/checks.yml',
    '.github/workflows/publish-images.yml', '.github/workflows/release.yml', 'scripts/prepare_buildkit.sh',
    '.github/workflows/quality.yml', 'ruff.toml', 'requirements-lint.txt',
    '.github/workflows/security.yml', '.github/codeql/config.yml', 'requirements-security.txt',
    'backend/requirements.in', 'scripts/check_sarif.py',
    '.github/workflows/browser-tests.yml', 'compose.e2e.yml', 'scripts/run_e2e.py',
    'frontend/playwright.config.js', 'frontend/e2e/portal.spec.js',
    'frontend/eslint.config.js',
    '.github/dependabot.yml',
    'compose.build.yml', 'docs/containers.md', 'scripts/init-env.sh',
    'docs/secrets.md',
    '.github/release-notes.md', 'scripts/prepare_release.py',
    '.github/workflows/release-verification.yml', '.github/trivy-release-ignore.yaml',
    'scripts/check_release_tag.py',
    'scripts/release_images.py', 'scripts/smoke_release.py', 'compose.release-smoke.yml',
    'docs/github-actions.md',
    'backend/app/services/media/__init__.py',
    'frontend/src/components/backgrounds/BackgroundPicker.vue',
)


def git(arguments, git_dir=None):
    prefix = ['git'] + ([f'--git-dir={git_dir}', f'--work-tree={ROOT}'] if git_dir else [])
    return subprocess.run(prefix + arguments, cwd=ROOT, capture_output=True, check=True)


@contextmanager
def repository():
    result = subprocess.run(['git', 'rev-parse', '--show-toplevel'], cwd=ROOT, capture_output=True, text=True)
    if result.returncode == 0:
        yield None, True
    else:
        # A temporary bare repository lets Git itself apply this project's ignore
        # rules, even before the owner initializes a repository here.
        with tempfile.TemporaryDirectory(prefix='catppuccindock-publish-') as directory:
            subprocess.run(['git', 'init', '--bare', '--quiet', directory], check=True, capture_output=True)
            yield directory, False


def ignored(path, git_dir):
    prefix = ['git'] + ([f'--git-dir={git_dir}', f'--work-tree={ROOT}'] if git_dir else [])
    result = subprocess.run(prefix + ['check-ignore', '--no-index', '--quiet', '--', path], cwd=ROOT, capture_output=True)
    if result.returncode not in (0, 1):
        raise RuntimeError('Git ignore evaluation failed')
    return result.returncode == 0


def values_from(path):
    if not path.is_file():
        return {}
    values = {}
    for line in path.read_text(encoding='utf-8').splitlines():
        key, separator, value = line.partition('=')
        key = key.strip().removeprefix('export ')
        if separator and SECRET_KEY.search(key) and not key.startswith('#'):
            values[key] = value.strip().strip('\"\'')
    return values


def local_secrets():
    known = {}
    for directory in (ROOT, ROOT/'frontend', ROOT/'backend'):
        paths = set(directory.glob('.env*')) | set(directory.glob('*.env')) | set(directory.glob('*.env.*'))
        for path in paths:
            if path.name.endswith('.example'):
                continue
            for key, value in values_from(path).items():
                if len(value) >= 8:
                    known.setdefault(value.encode(), set()).add(key)
    return known


def write_archive(target, contents):
    """Package the scanned bytes, rather than rereading potentially changed files."""
    target.parent.mkdir(parents=True, exist_ok=True)
    with target.open('xb') as output:
        target.chmod(0o600)
        try:
            with tarfile.open(fileobj=output, mode='w:gz') as archive:
                for name, content, mode in contents:
                    entry = tarfile.TarInfo('CatppuccinDock/'+name)
                    entry.mode = mode
                    entry.size = len(content)
                    archive.addfile(entry, io.BytesIO(content))
        except BaseException:
            target.unlink(missing_ok=True)
            raise


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--archive', type=Path, help='Write checked sources to a new .tar.gz file; never overwrites an existing file.')
    args = parser.parse_args(argv)
    failures = []
    contents = []
    with repository() as (git_dir, initialized):
        if args.archive:
            args.archive = args.archive.expanduser().resolve()
            if not args.archive.name.endswith('.tar.gz'):
                parser.error('--archive must end with .tar.gz')
            if args.archive.exists():
                parser.error('--archive target already exists; choose a new filename')
            if args.archive.is_relative_to(ROOT) and not ignored(args.archive.relative_to(ROOT).as_posix(), git_dir):
                parser.error('--archive inside the project must use an ignored directory, such as .local-backups/')
        names = git(['ls-files', '--cached', '--others', '--exclude-standard', '-z', '--', '.'], git_dir).stdout
        candidates = sorted(set(part.decode() for part in names.split(b'\0') if part))
        for path in EXCLUDED_SAMPLES:
            if not ignored(path, git_dir):
                failures.append((path, 'runtime/credential example is not ignored'))
        for path in PUBLISHABLE_SAMPLES:
            if ignored(path, git_dir):
                failures.append((path, 'source/template example is ignored'))
        for path in REQUIRED_FILES:
            if not (ROOT/path).is_file() or ignored(path, git_dir):
                failures.append((path, 'required source/template missing or ignored'))
        if initialized:
            tracked = git(['ls-files', '--cached', '--ignored', '--exclude-standard', '-z', '--', '.'], git_dir).stdout
            failures.extend((name.decode(), 'ignored file is already tracked') for name in tracked.split(b'\0') if name)
        secrets = local_secrets()
        for name in candidates:
            path = ROOT/name
            if path.is_symlink():
                failures.append((name, 'review symlink before publishing'))
                continue
            if not path.exists():
                continue
            if path.name.startswith('.env') and not path.name.endswith('.example'):
                failures.append((name, 'local environment file in Git candidates'))
            if path.suffix.lower() in BLOCKED_SUFFIXES:
                failures.append((name, 'credential/database file in Git candidates'))
            if path.suffix.lower() == '.sql' and not name.startswith('backend/app/db/'):
                failures.append((name, 'SQL file outside database source directory'))
            content = path.read_bytes()
            if args.archive:
                contents.append((name, content, 0o755 if path.stat().st_mode & 0o111 else 0o644))
            for label, pattern in MARKERS.items():
                if pattern.search(content):
                    failures.append((name, label+' detected'))
            for secret, keys in secrets.items():
                if secret in content:
                    failures.append((name, 'contains local environment value for '+','.join(sorted(keys))))
    if failures:
        for name, reason in sorted(set(failures)):
            print(f'FAIL {name}: {reason}')
        return 1
    if args.archive:
        write_archive(args.archive, contents)
        print(f'Checked source archive: {args.archive} ({len(contents)} files)')
    print(f'PASS: {len(candidates)} Git candidate files checked; {len(EXCLUDED_SAMPLES)} excluded-path checks passed.')
    print(f'PASS: {len(PUBLISHABLE_SAMPLES)} source/template rules, required docs, lockfile and bundled license are publishable.')
    print('No common credential markers or local .env secret values found in candidates.')
    if not initialized:
        print('Git is not initialized here; ignore rules were checked with temporary Git metadata.')
    print('Commit history was not scanned; no files were staged or published.')
    return 0


if __name__ == '__main__':
    sys.exit(main())
