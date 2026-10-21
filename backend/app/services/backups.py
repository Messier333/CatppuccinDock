"""Portable configuration backups, password encryption and owned import plans."""
import base64
import hashlib
import json
import secrets
import time
from threading import BoundedSemaphore
from datetime import datetime, timezone

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.scrypt import Scrypt
from fastapi import HTTPException
from pydantic import ValidationError
from sqlalchemy import delete, func, select

from app.core.security import cipher
from app.db.models import BackgroundImage, Bookmark, Category, OperationPreview, PersonalPreference, Setting, SharedLink, SharedPlacement, Tab, User, UploadedIcon
from app.schemas.backups import BackupDocument
from app.services.media.backgrounds import MAX_FILES, inspect_gif
from app.services.media import media_policy, storage, uploaded_icons
from app.services.icons import validate_icon
from app.services.library import allowed_link_ids
from app.services.proxy import url_key
from app.services.trash import erase, remember, snapshot

MAX_DOCUMENT = 384*1024*1024
crypto_slots = BoundedSemaphore(1)
AAD = b'CatppuccinDock.backup.v1/AES-256-GCM/scrypt-131072-8-1'

def encode(data): return base64.b64encode(data).decode('ascii')
def decode(data): return base64.b64decode(data, validate=True)
def serialized(data): return json.dumps(data, ensure_ascii=False, separators=(',',':')).encode()

def password_key(password, salt):
    with crypto_slots:
        return Scrypt(salt=salt, length=32, n=131072, r=8, p=1).derive(password.encode('utf-8'))

def encrypt_document(document, password):
    salt, nonce = secrets.token_bytes(16), secrets.token_bytes(12)
    body = AESGCM(password_key(password,salt)).encrypt(nonce,serialized(document),AAD)
    return {'format':'CatppuccinDock.encrypted','version':1,'cipher':'AES-256-GCM','kdf':'scrypt-131072-8-1','salt':encode(salt),'nonce':encode(nonce),'ciphertext':encode(body)}

def open_document(document, password):
    if not isinstance(document,dict): raise HTTPException(422,'올바른 백업 JSON을 선택해 주세요.')
    if document.get('format')=='CatppuccinDock.encrypted':
        try:
            if not password or len(password)>256 or document.get('version')!=1 or document.get('cipher')!='AES-256-GCM' or document.get('kdf')!='scrypt-131072-8-1':
                raise ValueError('Invalid envelope')
            salt,nonce = decode(document['salt']),decode(document['nonce'])
            if len(salt)!=16 or len(nonce)!=12: raise ValueError('Invalid envelope')
            document = json.loads(AESGCM(password_key(password,salt)).decrypt(nonce,decode(document['ciphertext']),AAD))
        except (ValueError,TypeError,KeyError,InvalidTag,RecursionError) as error:
            raise HTTPException(422,'암호가 올바르지 않거나 백업 파일이 손상되었습니다.') from error
    try:
        validated = BackupDocument.model_validate(document)
        for tab in validated.tabs:
            for category in tab.categories:
                for link in category.links: validate_icon(link.icon, uploaded_keys={icon.key for icon in validated.icons})
        for image in validated.images: inspect_gif(decode(image.data))
        for icon in validated.icons:
            uploaded_icons.icon_id(icon.key)
            uploaded_icons.inspect(decode(icon.data))
        return validated.model_dump(mode='json')
    except (ValueError, TypeError, OSError, SyntaxError, ValidationError, RecursionError) as error:
        raise HTTPException(422,'지원하는 CatppuccinDock 백업 형식인지 확인해 주세요.') from error

def global_settings(config):
    return {'search_engine':config['search']['default'],'search_open_mode':config['search'].get('openMode','same_tab'),'clock_format':config['clock']['format'],
        'timezone':config['clock'].get('timezone','Asia/Seoul'),'weather_location':config['temperature']['location'],
        'temperature_scale':config['temperature']['scale'],'tab_animation':config.get('tabAnimation',True),
        'bookmark_shelf_display':config.get('bookmarkShelfDisplay','labels')}

def export_document(db,user,include_images=True,include_settings=False):
    data = snapshot(db,user.id)
    shared = {row['bookmark_id']:row['link_id'] for row in data['placements']}
    allowed = allowed_link_ids(db,user)
    images = list(db.scalars(select(BackgroundImage).where(BackgroundImage.user_id==user.id).order_by(BackgroundImage.created_at,BackgroundImage.id))) if include_images else []
    image_ids = {row.id for row in images}
    personal = db.get(PersonalPreference,user.id)
    shared_rows = {row.id:row for row in db.scalars(select(SharedLink).where(SharedLink.id.in_(allowed)))}
    def links(category_id):
        output = []
        for row in sorted((item for item in data['bookmarks'] if item['category_id']==category_id),key=lambda item:(item['position'],item['id'])):
            ref = shared.get(row['id'])
            if ref and ref not in allowed: continue
            output.append({key:row[key] for key in ('name','url','icon','icon_color','favorite')} | {'url':shared_rows[ref].url if ref else row['url'],'shared_link_id':ref,
                'icon': 'world' if not include_images and row['icon'].startswith('upload:') else row['icon']})
        return output
    document = {'format':'CatppuccinDock','version':1,'created_at':datetime.now(timezone.utc).isoformat(),
        'tabs':[{'name':tab['name'],'banner':tab['banner'],'background_key':tab['background_id'] if tab['background_id'] in image_ids else None,
            'categories':[{'name':category['name'],'links':links(category['id'])} for category in sorted(data['categories'],key=lambda row:(row['position'],row['id'])) if category['tab_id']==tab['id']]}
            for tab in sorted(data['tabs'],key=lambda row:(row['position'],row['id']))],
        'images':[{'key':row.id,'name':row.name,'data':encode(storage.read(row)),'source':row.source} for row in images],
        'settings':global_settings(db.get(Setting,'portal').value) if include_settings and user.role=='admin' else None,
        'preferences':personal.values if personal else {}}
    document['icons'] = []
    if include_images:
        needed = {link['icon'][7:] for tab in document['tabs'] for cat in tab['categories'] for link in cat['links'] if link['icon'].startswith('upload:')}
        own = set(db.scalars(select(UploadedIcon.id).where(UploadedIcon.user_id == user.id)))
        if len(own | needed) > uploaded_icons.MAX_FILES:
            raise HTTPException(409, '백업에 포함할 업로드 아이콘이 100개를 초과합니다. 사용하지 않는 아이콘을 정리하거나 이미지 포함을 해제해 주세요.')
        for identifier in sorted(own | needed):
            icon = uploaded_icons.find(db, 'upload:'+identifier, user)
            document['icons'].append({'key':'upload:'+icon.id, 'name':icon.name, 'data':encode(storage.read(icon))})
    return document

def fingerprint(db,user_id):
    return hashlib.sha256(serialized(snapshot(db,user_id))).hexdigest()

def stage(db,user,kind,document):
    db.execute(delete(OperationPreview).where(OperationPreview.expires_at < time.time()))
    db.execute(delete(OperationPreview).where(OperationPreview.user_id==user.id, OperationPreview.kind==kind))
    row = OperationPreview(id=secrets.token_urlsafe(24),user_id=user.id,kind=kind,payload_encrypted=cipher().encrypt(serialized(document)).decode(),fingerprint=fingerprint(db,user.id),expires_at=time.time()+600)
    db.add(row);db.flush()
    return row.id

def entries(document, existing=None, allowed=None):
    result=[]
    for tab in document['tabs']:
        for category in tab['categories']:
            for link in category['links']:
                ref=link.get('shared_link_id')
                result.append({'id':str(len(result)),'name':link['name'],'url':link['url'],'path':tab['name']+' / '+category['name'],
                    'existing':url_key(link['url']) in (existing or set()),'restricted':bool(ref and ref not in (allowed or set()))})
    return result

def apply(db,user,payload,kind):
    media_config=media_policy.policy(db,locked=True)
    db.scalar(select(User).where(User.id==user.id).with_for_update())
    row=db.scalar(select(OperationPreview).where(OperationPreview.id==payload.preview_id,OperationPreview.user_id==user.id,OperationPreview.kind==kind).with_for_update())
    if not row or row.expires_at < time.time():raise HTTPException(409,'미리 보기가 만료되었습니다. 파일을 다시 선택해 주세요.')
    if row.fingerprint!=fingerprint(db,user.id):raise HTTPException(409,'북마크 목록이 변경되었습니다. 다시 미리 보기를 실행해 주세요.')
    document=json.loads(cipher().decrypt(row.payload_encrypted.encode()))
    if payload.apply_settings and (user.role!='admin' or not document.get('settings')):raise HTTPException(403,'공통 포털 설정은 관리자만 복원할 수 있습니다.')
    valid_ids={item['id'] for item in entries(document)}
    chosen=set(payload.selected_ids) if payload.selected_ids is not None else valid_ids
    if not chosen.issubset(valid_ids):raise HTTPException(422,'미리 보기에 없는 항목이 선택되었습니다.')
    previous=snapshot(db,user.id) if payload.mode=='replace' else None
    if previous:erase(db,previous)
    custom_icons={}
    for icon in document.get('icons', []):
        raw = decode(icon['data'])
        current = uploaded_icons.store(db, user, raw, icon['name'])
        custom_icons[icon['key']] = 'upload:'+current.id
    images={}
    for image in document.get('images',[]):
        raw=decode(image['data']);digest=hashlib.sha256(raw).hexdigest()
        current=db.scalar(select(BackgroundImage).where(BackgroundImage.user_id==user.id,BackgroundImage.sha256==digest))
        if not current:
            if db.scalar(select(func.count()).select_from(BackgroundImage).where(BackgroundImage.user_id==user.id))>=MAX_FILES:
                raise HTTPException(409,'GIF 저장 한도를 초과합니다. 미사용 배경을 정리한 뒤 다시 시도해 주세요.')
            media_policy.check_storage(db,user,media_config,len(raw))
            width,height,frames=inspect_gif(raw)
            current=BackgroundImage(user_id=user.id,name=image['name'],sha256=digest,byte_size=len(raw),width=width,height=height,frames=frames,source=image.get('source'))
            storage.write(db,current,raw)
            db.add(current);db.flush()
        images[image['key']]=current.id
    existing={url_key(url) for url in db.scalars(select(Bookmark.url).where(Bookmark.user_id==user.id))}
    allowed=allowed_link_ids(db,user)
    added,duplicates,restricted,index=0,0,0,0
    tabs=list(db.scalars(select(Tab).where(Tab.user_id==user.id).order_by(Tab.position,Tab.id)))
    for item in document['tabs']:
        tab=next((value for value in tabs if value.name==item['name']),None) if payload.mode=='merge' else None
        if not tab:
            tab=Tab(user_id=user.id,name=item['name'],banner=item['banner'],background_id=images.get(item.get('background_key')),position=len(tabs))
            db.add(tab);db.flush();tabs.append(tab)
        categories=list(db.scalars(select(Category).where(Category.tab_id==tab.id).order_by(Category.position,Category.id)))
        for group in item['categories']:
            category=next((value for value in categories if value.name==group['name']),None) if payload.mode=='merge' else None
            if not category:
                category=Category(user_id=user.id,tab_id=tab.id,name=group['name'],position=len(categories));db.add(category);db.flush();categories.append(category)
            position=db.scalar(select(func.max(Bookmark.position)).where(Bookmark.category_id==category.id))
            position=0 if position is None else position+1
            for link in group['links']:
                key=str(index);index+=1
                if key not in chosen:continue
                ref=link.get('shared_link_id')
                if ref and ref not in allowed:restricted+=1;continue
                url=db.get(SharedLink,ref).url if ref else str(link['url'])
                if payload.mode=='merge' and url_key(url) in existing:duplicates+=1;continue
                existing.add(url_key(url))
                bookmark=Bookmark(user_id=user.id,category_id=category.id,name=link['name'],url=url,icon=custom_icons.get(link['icon'], link['icon']),icon_color=link['icon_color'],favorite=link.get('favorite',False),position=min(position,10000))
                position+=1;db.add(bookmark);db.flush()
                if ref:db.add(SharedPlacement(bookmark_id=bookmark.id,link_id=ref))
                added+=1
    previous_settings = None
    expected_settings = None
    if payload.apply_settings:
        from copy import deepcopy
        setting=db.scalar(select(Setting).where(Setting.key=='portal').with_for_update())
        previous_settings = deepcopy(setting.value)
        config=deepcopy(setting.value);source=document['settings']
        config['clock']['format']=source['clock_format'];config['clock']['timezone']=source['timezone']
        config['search']['default']=source['search_engine'];config['temperature']['location']=source['weather_location'];config['temperature']['scale']=source['temperature_scale']
        config['search']['openMode']=source.get('search_open_mode','same_tab')
        config['tabAnimation']=source['tab_animation']
        config['bookmarkShelfDisplay']=source.get('bookmark_shelf_display','labels')
        setting.value=config
        expected_settings = deepcopy(config)
    db.flush()
    previous_preferences = expected_preferences = None
    if document.get('preferences') is not None:
        personal=db.get(PersonalPreference,user.id)
        previous_preferences=dict(personal.values) if personal else {}
        expected_preferences={key:value for key,value in document['preferences'].items() if value is not None}
        if personal: personal.values=expected_preferences
        else: db.add(PersonalPreference(user_id=user.id,values=expected_preferences))
    undo_id=remember(db,user.id,'replace','백업 복원 전 구성',{'previous':previous,'expected':snapshot(db,user.id),'previous_settings':previous_settings,'expected_settings':expected_settings,'previous_preferences':previous_preferences,'expected_preferences':expected_preferences}) if previous else None
    db.delete(row)
    return {'added':added,'duplicates':duplicates,'restricted':restricted,'undo_id':undo_id}
