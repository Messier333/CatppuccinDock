#!/usr/bin/env python3
"""Prepare public deployment files and version-specific release instructions."""
import argparse
import hashlib
import io
from pathlib import Path
import re
import tarfile

ROOT = Path(__file__).resolve().parents[1]
BUNDLE_FILES = (
    'docker-compose.yml', '.env.example',
)
SECRET_KEYS = {
    'POSTGRES_PASSWORD', 'ADMIN_SETUP_CODE', 'AUTH_ENCRYPTION_KEY',
    'S3_ACCESS_KEY_ID', 'S3_SECRET_ACCESS_KEY', 'GARAGE_RPC_SECRET',
}
VERSION = re.compile(r'v(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)(?:-[0-9A-Za-z.-]+)?(?:\+[0-9A-Za-z.-]+)?')
REPOSITORY = re.compile(r'[A-Za-z0-9][A-Za-z0-9-]*/[A-Za-z0-9_.-]+')


def prepare(tag, repository, output):
    if not VERSION.fullmatch(tag) or not REPOSITORY.fullmatch(repository):
        raise ValueError('Expected a v1.0.0-style tag and owner/repository name.')
    version = tag.removeprefix('v').split('+')[0]
    image_prefix = 'ghcr.io/'+repository.lower()
    asset = f'CatppuccinDock-{tag}-deploy.tar.gz'
    replacements = {
        '@@TAG@@': tag, '@@VERSION@@': version, '@@REPOSITORY@@': repository,
        '@@IMAGE_PREFIX@@': image_prefix, '@@ASSET@@': asset,
    }
    notes = (ROOT/'.github/release-notes.md').read_text(encoding='utf-8')
    for key, value in replacements.items():
        notes = notes.replace(key, value)
    files = {name: (ROOT/name).read_bytes() for name in BUNDLE_FILES}
    lines = []
    for line in files['.env.example'].decode().splitlines():
        key, separator, value = line.partition('=')
        if separator and key.strip() in SECRET_KEYS and value.strip().strip('\"\''):
            raise ValueError('Deployment environment examples must have blank credentials.')
        if key == 'IMAGE_TAG':
            line = 'IMAGE_TAG='+version
        elif key == 'GHCR_IMAGE_PREFIX':
            line = 'GHCR_IMAGE_PREFIX='+image_prefix
        lines.append(line)
    files['.env.example'] = ('\n'.join(lines)+'\n').encode()
    files['DEPLOY.md'] = notes.encode()

    output = Path(output)
    output.mkdir(parents=True, exist_ok=False)
    (output/'release-notes.md').write_text(notes, encoding='utf-8')
    with tarfile.open(output/asset, 'w:gz') as archive:
        for name, content in files.items():
            entry = tarfile.TarInfo(name)
            entry.mode = 0o644
            entry.size = len(content)
            archive.addfile(entry, io.BytesIO(content))
    attachments = [asset, 'docker-compose.yml', '.env.example']
    for name in attachments[1:]:
        (output/name).write_bytes(files[name])
    checksums = [hashlib.sha256((output/name).read_bytes()).hexdigest()+'  '+name for name in attachments]
    (output/'SHA256SUMS').write_text('\n'.join(checksums)+'\n')
    return attachments+['SHA256SUMS']


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--tag', required=True)
    parser.add_argument('--repository', required=True)
    parser.add_argument('--output', required=True, type=Path)
    args = parser.parse_args()
    for name in prepare(args.tag, args.repository, args.output):
        print('Prepared '+name)


if __name__ == '__main__':
    main()
