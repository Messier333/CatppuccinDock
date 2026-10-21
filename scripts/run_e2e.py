#!/usr/bin/env python3
"""Run browser tests against a disposable PostgreSQL/Garage Compose project."""
import argparse
import base64
import os
from pathlib import Path
import secrets
import subprocess
import sys
import time
from urllib.error import URLError
from urllib.request import urlopen

ROOT = Path(__file__).resolve().parents[1]


def run(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--port', type=int, default=18090)
    parser.add_argument('--browser-image', help='Run Playwright in its matching official Docker image instead of host Node.js.')
    args = parser.parse_args(argv)
    if not 1024 <= args.port <= 65535 or args.port == 8090:
        parser.error('Choose a test port from 1024–65535, excluding the production default 8090.')

    # Never load the checkout's .env or share its Compose project/volumes/bind mounts.
    project = 'catppuccindock-e2e-'+secrets.token_hex(6)
    env = {
        **os.environ,
        'POSTGRES_DB': 'browser_test', 'POSTGRES_USER': 'browser_test',
        'POSTGRES_PASSWORD': secrets.token_hex(32),
        'ADMIN_SETUP_CODE': secrets.token_hex(32),
        'AUTH_ENCRYPTION_KEY': base64.urlsafe_b64encode(secrets.token_bytes(32)).decode(),
        'GARAGE_RPC_SECRET': secrets.token_hex(32),
        'COOKIE_SECURE': 'false', 'MEDIA_STORAGE_BACKEND': 's3',
        'S3_ENDPOINT_URL': 'http://garage:3900', 'S3_REGION': 'garage',
        'S3_ACCESS_KEY_ID': 'GK'+secrets.token_hex(12),
        'S3_SECRET_ACCESS_KEY': secrets.token_hex(32),
        'S3_BUCKET': 'browser-test', 'S3_KEY_PREFIX': 'browser-test',
        'PORTAL_PORT': f'127.0.0.1:{args.port}',
        'E2E_BASE_URL': f'http://127.0.0.1:{args.port}',
        'E2E_USERNAME': 'browser-owner', 'E2E_PASSWORD': secrets.token_urlsafe(24),
    }
    env['E2E_SETUP_CODE'] = env['ADMIN_SETUP_CODE']
    compose = [
        'docker', 'compose', '--env-file', '/dev/null', '-p', project,
        '-f', 'docker-compose.yml', '-f', 'compose.e2e.yml',
    ]
    artifacts = ROOT/'frontend/test-results'
    artifacts.mkdir(parents=True, exist_ok=True)
    status = 1
    try:
        print(f'Starting isolated browser test project {project}', flush=True)
        subprocess.run(compose+['up', '--build', '-d', '--wait', '--wait-timeout', '240'], cwd=ROOT, env=env, check=True)
        for attempt in range(30):
            try:
                with urlopen(env['E2E_BASE_URL']+'/api/health', timeout=3) as response:
                    if response.status == 200:
                        break
            except (OSError, URLError):
                if attempt == 29:
                    raise RuntimeError('Test frontend did not become ready.') from None
                time.sleep(1)

        command = ['npm', '--prefix', 'frontend', 'run', 'test:e2e']
        if args.browser_image:
            # Browser receives only fixture login details, never S3/database credentials.
            command = ['docker', 'run', '--rm', '--network', 'host', '--ipc=host',
                       '--user', f'{os.getuid()}:{os.getgid()}',
                       '-v', f'{ROOT / "frontend"}:/work:ro',
                       '-v', f'{artifacts}:/artifacts', '-w', '/work']
            for key in ('E2E_BASE_URL', 'E2E_USERNAME', 'E2E_PASSWORD', 'E2E_SETUP_CODE', 'CI'):
                if key in env:
                    command += ['-e', key]
            command += [args.browser_image, './node_modules/.bin/playwright', 'test', '--output=/artifacts/results']
        status = subprocess.run(command, cwd=ROOT, env=env, check=False).returncode
    except (subprocess.CalledProcessError, OSError, RuntimeError) as error:
        print(f'Browser test stack failed: {type(error).__name__}', file=sys.stderr)
    finally:
        if status:
            # Generated fixture credentials are not written into the repository.
            # Omit logs entirely: auth logs can contain account/session information.
            result = subprocess.run(compose+['ps', '--all'], cwd=ROOT, env=env, capture_output=True, text=True, check=False)
            (artifacts/'stack-status.txt').write_text(result.stdout+result.stderr)
        print(f'Removing disposable project {project} and its test volumes', flush=True)
        cleanup = subprocess.run(compose+['down', '--volumes', '--remove-orphans'], cwd=ROOT, env=env, check=False)
        if cleanup.returncode:
            print('Test stack cleanup failed; remove only the project named above.', file=sys.stderr)
            status = 1
    return status


if __name__ == '__main__':
    sys.exit(run())
