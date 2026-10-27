#!/usr/bin/env python3
"""Reject release tags outside main or different from the workflow commit."""
import argparse
import re
import subprocess

NUMBER = r'(?:0|[1-9][0-9]*)'
PRERELEASE_ID = rf'(?:{NUMBER}|[0-9]*[A-Za-z-][0-9A-Za-z-]*)'
VERSION = re.compile(
    rf'v{NUMBER}\.{NUMBER}\.{NUMBER}'
    rf'(?:-{PRERELEASE_ID}(?:\.{PRERELEASE_ID})*)?'
    r'(?:\+[0-9A-Za-z-]+(?:\.[0-9A-Za-z-]+)*)?'
)


def git(*arguments):
    return subprocess.run(['git', *arguments], check=True, capture_output=True, text=True).stdout.strip()


def validate(tag, commit):
    if not VERSION.fullmatch(tag) or len(tag.removeprefix('v').split('+')[0]) > 128:
        raise ValueError('Expected a v1.2.3-style SemVer tag with a valid container version.')
    if not re.fullmatch('[0-9a-f]{40}', commit):
        raise ValueError('Expected the full workflow commit SHA.')
    target = git('rev-parse', '--verify', f'refs/tags/{tag}^{{commit}}')
    if target != commit or git('rev-parse', 'HEAD') != commit:
        raise ValueError('Release tag, checked-out source and workflow commit must match.')
    main = git('rev-parse', '--verify', 'refs/remotes/origin/main^{commit}')
    result = subprocess.run(['git', 'merge-base', '--is-ancestor', target, main], capture_output=True)
    if result.returncode == 1:
        raise ValueError('Release commit is not in origin/main. Merge the PR before tagging.')
    result.check_returncode()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--tag', required=True)
    parser.add_argument('--commit', required=True)
    args = parser.parse_args()
    validate(args.tag, args.commit)
    print(f'PASS: {args.tag} identifies the checked-out commit and belongs to origin/main.')


if __name__ == '__main__':
    main()
