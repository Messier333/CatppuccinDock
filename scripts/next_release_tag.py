#!/usr/bin/env python3
"""Select the next stable release tag, reusing a tag on the current commit."""
import re
import subprocess

STABLE_VERSION = re.compile(r'v(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)')


def stable_versions(tags):
    return {
        tuple(map(int, match.groups())): tag
        for tag in tags
        if (match := STABLE_VERSION.fullmatch(tag))
    }


def next_release_tag(tags, current_tags):
    current = stable_versions(current_tags)
    if current:
        return current[max(current)]
    versions = stable_versions(tags)
    if not versions:
        return 'v1.0.0'
    major, minor, patch = max(versions)
    return f'v{major}.{minor}.{patch+1}'


def git_tags(*arguments):
    return subprocess.run(
        ['git', 'tag', *arguments], check=True, capture_output=True, text=True,
    ).stdout.splitlines()


if __name__ == '__main__':
    print(next_release_tag(git_tags('--list'), git_tags('--points-at', 'HEAD')))
