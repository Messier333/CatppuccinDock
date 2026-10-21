import secrets,time
from typing import Literal
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel,ConfigDict,Field
from sqlalchemy import select
from app.api.dependencies import require_admin,require_mutation_header
from app.api.proxy import find_source
from app.db.models import ProxySync,Setting,SharedLink
from app.db.session import SessionLocal
from app.schemas.proxy import PreviewData
from app.services.proxy_sync import changes,representation,run_sync

router=APIRouter(prefix='/api/admin/proxy-sources',dependencies=[Depends(require_admin)])

class SyncData(PreviewData):
    enabled:bool=False
    interval:int=Field(default=900,ge=300,le=86400)

class ReviewData(BaseModel):
    model_config=ConfigDict(extra='forbid')
    revision:str=Field(min_length=1,max_length=64)
    change_ids:list[str]=Field(min_length=1,max_length=2000)
    action:Literal['apply','ignore']='apply'

@router.get('/{source_id}/sync')
def config(source_id:str):
    with SessionLocal() as db:
        source=find_source(db,source_id)
        row=db.get(ProxySync,source_id)
        return representation(row) if row else {'source_id':source_id,'enabled':False,'interval':900,'scheme':'https' if source.provider=='zoraxy' else 'auto','public_port':None,'revision':'','checked_at':None,'next_check':0,'error':'','changes':[]}

@router.put('/{source_id}/sync',dependencies=[Depends(require_mutation_header)])
def configure(source_id:str,payload:SyncData):
    with SessionLocal.begin() as db:
        source=find_source(db,source_id)
        if source.provider=='zoraxy' and payload.scheme=='auto':raise HTTPException(422,'Zoraxy는 HTTP 또는 HTTPS를 선택해 주세요.')
        row=db.get(ProxySync,source_id)
        if not row:
            row=ProxySync(source_id=source_id,baseline=[{'name':link.name,'url':link.url} for link in db.scalars(select(SharedLink).where(SharedLink.source_id==source_id))],inventory=[])
            db.add(row)
        for key,value in payload.model_dump().items():setattr(row,key,value)
        row.revision=secrets.token_hex(16);row.next_check=0;row.error='';row.checked_at=None
        db.flush();return representation(row)

@router.post('/{source_id}/sync/check',dependencies=[Depends(require_mutation_header)])
def check(source_id:str):
    with SessionLocal() as db:
        find_source(db,source_id);row=db.get(ProxySync,source_id)
        if not row:raise HTTPException(409,'먼저 변경 감지 설정을 저장해 주세요.')
        if row.checked_at and row.checked_at>time.time()-15:raise HTTPException(409,'잠시 후 다시 확인해 주세요.')
    run_sync(source_id,force=True)
    return config(source_id)

@router.post('/{source_id}/sync/review',dependencies=[Depends(require_mutation_header)])
def review(source_id:str,payload:ReviewData):
    with SessionLocal.begin() as db:
        source=find_source(db,source_id)
        row=db.scalar(select(ProxySync).where(ProxySync.source_id==source_id).with_for_update())
        if not row or row.revision!=payload.revision or row.error:raise HTTPException(409,'목록이 변경되었습니다. 새로고침 후 다시 검토해 주세요.')
        pending={item['id']:item for item in changes(row)}
        if not set(payload.change_ids).issubset(pending):raise HTTPException(422,'현재 변경 목록에서 선택해 주세요.')
        db.scalar(select(Setting).where(Setting.key=='portal').with_for_update())
        baseline={item['url']:item for item in row.baseline}
        applied=0
        for item_id in dict.fromkeys(payload.change_ids):
            item=pending[item_id];url=item['url']
            if payload.action=='apply':
                link=db.scalar(select(SharedLink).where(SharedLink.url==url).with_for_update())
                if item['kind']=='added':
                    if link and link.source_id not in (None,source_id):raise HTTPException(409,'다른 서비스에서 관리 중인 링크입니다. 공개 링크 관리에서 확인해 주세요.')
                    if not link:
                        link=SharedLink(source_id=source_id,source_name=source.name,name=item['name'],url=url,published=True);db.add(link)
                    else:link.published=True;link.source_id=source_id;link.source_name=source.name
                    applied+=1
                elif link and link.source_id==source_id:
                    if item['kind']=='removed':link.published=False
                    else:link.name=item['name']
                    applied+=1
            if item['kind']=='removed':baseline.pop(url,None)
            else:baseline[url]={'name':item['name'],'url':url}
        row.baseline=list(baseline.values());row.revision=secrets.token_hex(16)
        db.flush();return representation(row) | {'applied':applied,'reviewed':len(set(payload.change_ids))}
