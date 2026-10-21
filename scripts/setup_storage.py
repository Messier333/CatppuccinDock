#!/usr/bin/env python3
"""Append missing local Garage credentials without printing or replacing secrets."""
import os
from pathlib import Path
import secrets

ROOT = Path(__file__).resolve().parents[1]


def main():
    target = ROOT / '.env'
    if not target.is_file():
        raise SystemExit('먼저 .env.example을 .env로 복사하고 DB·로그인 설정을 입력하세요.')
    text = target.read_text()
    existing = {}
    for line in text.splitlines():
        key, separator, value = line.partition('=')
        if separator and not key.strip().startswith('#'):
            existing[key.strip()] = value.strip().strip('\"\'')
    generated = {
        'GARAGE_RPC_SECRET': secrets.token_hex(32),
        'S3_ACCESS_KEY_ID': 'GK' + secrets.token_hex(16),
        'S3_SECRET_ACCESS_KEY': secrets.token_hex(32),
    }
    # Blank template values are filled in place. Existing credentials stay intact.
    lines = text.splitlines()
    for key, value in generated.items():
        if existing.get(key):
            continue
        lines = [line for line in lines if line.partition('=')[0].strip() != key]
        lines.append(f'{key}={value}')
    for key, value in {'MEDIA_STORAGE_BACKEND':'s3','S3_ENDPOINT_URL':'http://garage:3900','S3_REGION':'garage','S3_BUCKET':'catppuccindock','S3_KEY_PREFIX':'catppuccindock'}.items():
        if key not in existing:
            lines.append(f'{key}={value}')
    os.chmod(target, 0o600)
    target.write_text('\n'.join(lines) + '\n')
    print('Garage 설정을 .env에 준비했습니다. 기존 계정·DB·암호화 키는 유지했습니다.')


if __name__ == '__main__':
    main()
