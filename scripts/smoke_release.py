#!/usr/bin/env python3
"""Run the published image pair in an isolated, disposable Compose project."""
import argparse
import base64
import json
import os
from pathlib import Path
import re
import secrets
import subprocess
import sys
import tempfile
import time
from urllib.error import URLError
from urllib.request import urlopen

from scripts.release_images import load_images

ROOT = Path(__file__).resolve().parents[1]


def check_http(base_url):
    with urlopen(base_url+'/', timeout=5) as response:
        if response.status != 200 or b'<html' not in response.read().lower():
            raise RuntimeError('Published frontend did not serve the application HTML.')
    with urlopen(base_url+'/api/health', timeout=5) as response:
        health = json.load(response)
        expected = {'status': 'ok', 'database': 'ok', 'storage': 's3'}
        if response.status != 200 or not isinstance(health, dict) or any(health.get(key) != value for key, value in expected.items()):
            raise RuntimeError('Published backend, database or storage is not healthy.')


def check_container_isolation(compose, environment, directory):
    network_memberships = {}
    details_by_service = {}
    for service in ('backend', 'frontend', 'database', 'garage'):
        container = subprocess.run(compose+['ps', '-q', service], cwd=directory, env=environment,
                                   capture_output=True, text=True, check=True).stdout.strip()
        if not container:
            raise RuntimeError(f'{service} container is missing.')
        details = json.loads(subprocess.run(['docker', 'inspect', container], cwd=directory,
                                            capture_output=True, text=True, check=True).stdout)[0]
        details_by_service[service] = details
        network_memberships[service] = set(details.get('NetworkSettings', {}).get('Networks', {}))

    for service in ('backend', 'frontend'):
        command = ['python', '-c', 'import os; assert os.geteuid() != 0'] if service == 'backend' else [
            'sh', '-c', 'test "$(id -u)" -ne 0',
        ]
        subprocess.run(compose+['exec', '-T', service, *command], cwd=directory,
                       env=environment, check=True, stdout=subprocess.DEVNULL)
        host = details_by_service[service]['HostConfig']
        if (not host.get('ReadonlyRootfs') or 'ALL' not in (host.get('CapDrop') or [])
                or host.get('PidsLimit') != 128 or '/tmp' not in (host.get('Tmpfs') or {})):
            raise RuntimeError(f'{service} container is missing filesystem, capability or process isolation.')
        if 'no-new-privileges:true' not in (host.get('SecurityOpt') or []):
            raise RuntimeError(f'{service} container can gain new privileges.')

    frontend = network_memberships['frontend']
    backend = network_memberships['backend']
    data = network_memberships['database']
    if (len(frontend) != 1 or len(data) != 1 or network_memberships['garage'] != data
            or not frontend.isdisjoint(data) or backend != frontend | data):
        raise RuntimeError('Frontend, backend, database and storage networks are not isolated.')
    data_details = json.loads(subprocess.run(['docker', 'network', 'inspect', next(iter(data))], cwd=directory,
                                             capture_output=True, text=True, check=True).stdout)[0]
    if not data_details.get('Internal'):
        raise RuntimeError('Database and storage network permits external traffic.')


def run_stack(images, platform):
    if platform not in ('linux/amd64', 'linux/arm64'):
        raise ValueError('Unsupported release smoke-test platform.')
    project = 'catppuccindock-release-'+secrets.token_hex(6)
    env = {
        **os.environ,
        'SMOKE_FRONTEND_IMAGE': images['frontend'], 'SMOKE_BACKEND_IMAGE': images['backend'],
        'SMOKE_PLATFORM': platform,
        'POSTGRES_DB': 'release_test', 'POSTGRES_USER': 'release_test',
        'POSTGRES_PASSWORD': secrets.token_hex(32), 'ADMIN_SETUP_CODE': secrets.token_hex(32),
        'AUTH_ENCRYPTION_KEY': base64.urlsafe_b64encode(secrets.token_bytes(32)).decode(),
        'GARAGE_RPC_SECRET': secrets.token_hex(32), 'COOKIE_SECURE': 'false',
        'MEDIA_STORAGE_BACKEND': 's3', 'S3_ENDPOINT_URL': 'http://garage:3900',
        'S3_REGION': 'garage', 'S3_BUCKET': 'release-test', 'S3_KEY_PREFIX': 'release-test',
        'S3_ACCESS_KEY_ID': 'GK'+secrets.token_hex(12), 'S3_SECRET_ACCESS_KEY': secrets.token_hex(32),
        'PORTAL_PORT': '127.0.0.1:0',
    }
    with tempfile.TemporaryDirectory(prefix='dock-release-smoke-') as directory:
        compose = [
            'docker', 'compose', '--env-file', '/dev/null', '--project-directory', directory,
            '-p', project, '-f', str(ROOT/'docker-compose.yml'), '-f', str(ROOT/'compose.release-smoke.yml'),
        ]
        status = 1
        try:
            subprocess.run(compose+['pull', '--quiet'], cwd=directory, env=env, check=True)
            subprocess.run(compose+[
                'up', '--no-build', '--pull', 'never', '-d', '--wait', '--wait-timeout', '300',
            ], cwd=directory, env=env, check=True)
            check_container_isolation(compose, env, directory)
            port = subprocess.run(compose+['port', 'frontend', '8080'], cwd=directory, env=env,
                                  capture_output=True, text=True, check=True).stdout.strip()
            if not re.fullmatch(r'127\.0\.0\.1:[1-9][0-9]*', port):
                raise RuntimeError('Release smoke-test port must be bound to localhost.')
            for attempt in range(30):
                try:
                    check_http('http://'+port)
                    break
                except (OSError, URLError, ValueError, RuntimeError):
                    if attempt == 29:
                        raise
                    time.sleep(1)
            print(f'PASS: published {platform} frontend and backend serve healthy HTTP responses.')
            status = 0
        except (subprocess.CalledProcessError, OSError, ValueError, RuntimeError) as error:
            print(f'Release smoke test failed: {type(error).__name__}', file=sys.stderr)
        finally:
            # Restrict cleanup to our generated project. Never collect auth logs or fixture credentials.
            cleanup = subprocess.run(compose+['down', '--volumes', '--remove-orphans'],
                                     cwd=directory, env=env, check=False)
            if cleanup.returncode:
                status = 1
                print(f'Cleanup failed for disposable project {project}.', file=sys.stderr)
        return status


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--images', required=True, type=Path)
    parser.add_argument('--repository', required=True)
    parser.add_argument('--commit', required=True)
    parser.add_argument('--platform', required=True, choices=('linux/amd64', 'linux/arm64'))
    args = parser.parse_args()
    images = load_images(args.images, args.repository, args.commit)
    return run_stack(images, args.platform)


if __name__ == '__main__':
    sys.exit(main())
