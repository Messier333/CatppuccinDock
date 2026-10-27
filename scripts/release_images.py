#!/usr/bin/env python3
"""Record and validate exact image digests shared by jobs in one release run."""
import argparse
import json
from pathlib import Path
import re

COMPONENTS = ('frontend', 'backend')


def validate(record, repository, commit):
    component = record.get('component')
    if component not in COMPONENTS or record.get('commit') != commit:
        raise ValueError('Unexpected image component or source commit in release artifact.')
    image = record.get('image')
    if image != f'ghcr.io/{repository.lower()}-{component}':
        raise ValueError('Image must belong to this repository and component.')
    digest = record.get('digest', '')
    if not isinstance(digest, str) or not re.fullmatch('sha256:[0-9a-f]{64}', digest):
        raise ValueError('A complete published SHA256 image digest is required.')
    return component, f'{image}@{digest}'


def record_image(directory, repository, commit, component, image, digest):
    record = {'component': component, 'image': image, 'digest': digest, 'commit': commit}
    validate(record, repository, commit)
    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=True)
    (directory/f'{component}.json').write_text(json.dumps(record)+'\n', encoding='utf-8')


def load_images(directory, repository, commit):
    images = {}
    for path in Path(directory).rglob('*.json'):
        record = json.loads(path.read_text(encoding='utf-8'))
        if not isinstance(record, dict):
            raise ValueError('Expected a release image record.')
        component, reference = validate(record, repository, commit)
        if component in images:
            raise ValueError('Duplicate image component in release artifacts.')
        images[component] = reference
    if set(images) != set(COMPONENTS):
        raise ValueError('Both frontend and backend image records are required.')
    return images


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('operation', choices=('record', 'read'))
    parser.add_argument('--directory', required=True, type=Path)
    parser.add_argument('--repository', required=True)
    parser.add_argument('--commit', required=True)
    parser.add_argument('--component', required=True, choices=COMPONENTS)
    parser.add_argument('--image')
    parser.add_argument('--digest')
    args = parser.parse_args()
    if args.operation == 'record':
        record_image(args.directory, args.repository, args.commit, args.component, args.image, args.digest)
    else:
        print(load_images(args.directory, args.repository, args.commit)[args.component])


if __name__ == '__main__':
    main()
