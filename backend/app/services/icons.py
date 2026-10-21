"""Search vendored Iconify collections and serve selected SVGs locally."""
import json
from functools import lru_cache
from importlib.resources import files

from fastapi import HTTPException


COLLECTIONS = {'tabler': 'Tabler · 기본 아이콘', 'simple-icons': 'Simple Icons · 앱·브랜드', 'mdi': 'Material Design Icons'}
KEYWORDS = {'서버': 'server', '도커': 'docker', '검색': 'search', '설정': 'settings', '홈': 'home', '집': 'home',
            '네트워크': 'network', '클라우드': 'cloud', '보안': 'shield', '음악': 'music', '동영상': 'video', '파일': 'file', '폴더': 'folder', '사진': 'photo'}


@lru_cache(maxsize=3)
def collection_data(prefix):
    if prefix not in COLLECTIONS:
        raise HTTPException(422, '지원하는 아이콘 컬렉션을 선택해 주세요.')
    return json.loads(files('app.data').joinpath('iconsets', prefix+'.json').read_text())


def validate_icon(name, *, db=None, user=None, uploaded_keys=None):
    if name.startswith('upload:'):
        from app.services.media import uploaded_icons
        uploaded_icons.icon_id(name)
        if uploaded_keys is not None:
            if name not in uploaded_keys:
                raise HTTPException(422, '백업에 업로드 아이콘 파일이 없습니다.')
        elif db is not None and user is not None:
            uploaded_icons.find(db, name, user, locked=True)
        else:
            raise HTTPException(422, '업로드 아이콘의 사용 권한을 확인할 수 없습니다.')
        return
    if ':' not in name:
        return
    prefix, icon = name.split(':', 1)
    if icon not in collection_data(prefix)['icons']:
        raise HTTPException(422, '아이콘 목록에서 유효한 아이콘을 선택해 주세요.')


def svg_for(name):
    validate_icon(name)
    if ':' not in name:
        raise HTTPException(404, '아이콘을 찾을 수 없습니다.')
    prefix, icon = name.split(':', 1)
    data = collection_data(prefix)
    entry = data['icons'][icon]
    width, height = entry.get('width', data.get('width', 24)), entry.get('height', data.get('height', 24))
    return f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {width} {height}" fill="currentColor">{entry["body"]}</svg>'
