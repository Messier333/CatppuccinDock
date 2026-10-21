import json
import asyncio
from fastapi import APIRouter, Depends, HTTPException, Request, Response
from pydantic import BaseModel, ConfigDict, Field, ValidationError
from sqlalchemy import select
from starlette.concurrency import run_in_threadpool
from app.api.dependencies import require_mutation_header, require_user
from app.db.models import Bookmark, User
from app.db.session import SessionLocal
from app.schemas.backups import ExportData, ImportApply
from app.services import backups
from app.services.browser_bookmarks import parse_bookmarks
from app.services.library import allowed_link_ids
from app.services.proxy import url_key

router=APIRouter(prefix='/api',dependencies=[Depends(require_user)])
upload_slots = asyncio.Semaphore(2)

@router.post('/backups/export',dependencies=[Depends(require_mutation_header)])
def export(payload:ExportData,user:User=Depends(require_user)):
    if payload.include_settings and user.role!='admin':raise HTTPException(403,'공통 설정은 관리자만 내보낼 수 있습니다.')
    with SessionLocal() as db:
        document=backups.export_document(db,user,payload.include_images,payload.include_settings)
    if payload.encrypted:document=backups.encrypt_document(document,payload.password)
    data=backups.serialized(document)
    if len(data)>backups.MAX_DOCUMENT:raise HTTPException(413,'백업이 너무 큽니다. GIF 포함을 해제한 뒤 다시 시도해 주세요.')
    return Response(data,media_type='application/json',headers={'Content-Disposition':'attachment; filename="catppuccindock'+('-encrypted' if payload.encrypted else '')+'.json"'})

async def read_payload(request,limit):
    data=bytearray()
    async for chunk in request.stream():
        data.extend(chunk)
        if len(data)>limit:raise HTTPException(413,'업로드 파일이 너무 큽니다.')
    try:return json.loads(data)
    except (ValueError,UnicodeError,RecursionError) as error:raise HTTPException(422,'올바른 JSON 요청이 아닙니다.') from error

class PreviewData(BaseModel):
    model_config=ConfigDict(extra='forbid')
    document:dict
    password:str=Field(default='',max_length=256)

class BrowserData(BaseModel):
    model_config=ConfigDict(extra='forbid')
    html:str=Field(max_length=5*1024*1024)


def preview(user,payload,kind):
    if kind=='backup':document=backups.open_document(payload.document,payload.password);skipped=0
    else:
        document,skipped=parse_bookmarks(payload.html)
        document=backups.open_document(document,'')
    with SessionLocal.begin() as db:
        existing={url_key(url) for url in db.scalars(select(Bookmark.url).where(Bookmark.user_id==user.id))}
        rows=backups.entries(document,existing,allowed_link_ids(db,user))
        preview_id=backups.stage(db,user,kind,document)
    seen=set();duplicates=0
    for row in rows:
        key=url_key(row['url'])
        row['duplicate_in_file']=key in seen
        if row['duplicate_in_file'] or row['existing']:duplicates+=1
        seen.add(key)
    return {'preview_id':preview_id,'kind':kind,'tabs':len(document['tabs']),'categories':sum(len(tab['categories']) for tab in document['tabs']),
        'bookmarks':len(rows),'images':len(document['images']),'icons':len(document.get('icons', [])),'has_settings':bool(document['settings']),'duplicates':duplicates,
        'restricted':sum(row['restricted'] for row in rows),'skipped':skipped,'entries':rows}

@router.post('/backups/import-preview',dependencies=[Depends(require_mutation_header)])
async def backup_preview(request:Request,user:User=Depends(require_user)):
    async with upload_slots:
        try:payload=PreviewData.model_validate(await read_payload(request,backups.MAX_DOCUMENT+1024))
        except ValidationError as error:raise HTTPException(422,'백업 파일과 암호를 확인해 주세요.') from error
        return await run_in_threadpool(preview,user,payload,'backup')

@router.post('/browser-bookmarks/preview',dependencies=[Depends(require_mutation_header)])
async def browser_preview(request:Request,user:User=Depends(require_user)):
    async with upload_slots:
        try:payload=BrowserData.model_validate(await read_payload(request,7*1024*1024))
        except ValidationError as error:raise HTTPException(422,'브라우저 북마크 HTML 파일을 확인해 주세요.') from error
        return await run_in_threadpool(preview,user,payload,'browser')

@router.post('/backups/import',dependencies=[Depends(require_mutation_header)])
def backup_import(payload:ImportApply,user:User=Depends(require_user)):
    with SessionLocal.begin() as db:return backups.apply(db,user,payload,'backup')

@router.post('/browser-bookmarks/import',dependencies=[Depends(require_mutation_header)])
def browser_import(payload:ImportApply,user:User=Depends(require_user)):
    if payload.mode!='merge' or payload.apply_settings:raise HTTPException(422,'브라우저 북마크는 선택한 항목을 병합하여 가져옵니다.')
    with SessionLocal.begin() as db:return backups.apply(db,user,payload,'browser')

@router.get('/browser-bookmarks/export')
def browser_export(user:User=Depends(require_user)):
    from html import escape
    with SessionLocal() as db:document=backups.export_document(db,user,False,False)
    lines=['<!DOCTYPE NETSCAPE-Bookmark-file-1>','<META HTTP-EQUIV="Content-Type" CONTENT="text/html; charset=UTF-8">','<TITLE>CatppuccinDock</TITLE>','<H1>CatppuccinDock</H1>','<DL><p>']
    for tab in document['tabs']:
        lines.extend(['<DT><H3>'+escape(tab['name'])+'</H3>','<DL><p>'])
        for category in tab['categories']:
            lines.extend(['<DT><H3>'+escape(category['name'])+'</H3>','<DL><p>'])
            for link in category['links']:lines.append('<DT><A HREF="'+escape(link['url'],quote=True)+'">'+escape(link['name'])+'</A>')
            lines.append('</DL><p>')
        lines.append('</DL><p>')
    lines.append('</DL><p>')
    return Response('\n'.join(lines),media_type='text/html',headers={'Content-Disposition':'attachment; filename="bookmarks.html"','Content-Security-Policy':"default-src 'none'; sandbox"})
