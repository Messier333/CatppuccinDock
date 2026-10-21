"""Inventories are observed automatically; publication changes require review."""
import hashlib,secrets,time
from fastapi import HTTPException
from sqlalchemy import select
from app.db.models import ProxySource, ProxySync
from app.db.session import SessionLocal
from app.schemas.proxy import PreviewData
from app.services.proxy import fetch_hosts, normalize_hosts, url_key


def changes(row):
    baseline={url_key(item['url']):item for item in row.baseline}
    current={url_key(item['url']):item for item in row.inventory}
    output=[]
    for url,item in current.items():
        kind='added' if url not in baseline else 'changed' if item['name']!=baseline[url]['name'] else None
        if kind:output.append({'kind':kind,'url':url,'name':item['name'],'previous_name':baseline.get(url,{}).get('name')})
    for url,item in baseline.items():
        if url not in current:output.append({'kind':'removed','url':url,'name':item['name'],'previous_name':item['name']})
    return [item | {'id':hashlib.sha256((item['kind']+'\0'+item['url']).encode()).hexdigest()} for item in output]


def representation(row):
    return {key:getattr(row,key) for key in ('source_id','enabled','interval','scheme','public_port','revision','checked_at','next_check','error')} | {'changes':changes(row) if row.checked_at is not None and not row.error else []}


def run_sync(source_id,force=False):
    with SessionLocal.begin() as db:
        row=db.scalar(select(ProxySync).where(ProxySync.source_id==source_id).with_for_update())
        source=db.get(ProxySource,source_id)
        if not row or not source or not force and (not row.enabled or row.next_check>time.time()):return
        revision=row.revision;source_revision=source.revision
        options=PreviewData(scheme=row.scheme,public_port=row.public_port)
        row.next_check=time.time()+row.interval
        db.expunge(source)
    error=''
    try:inventory,_=normalize_hosts(source.provider,fetch_hosts(source),options,source.custom_api)
    except HTTPException as failure:inventory=[];error=str(failure.detail)[:240]
    except Exception:inventory=[];error='서비스 API 응답을 확인하지 못했습니다.'
    with SessionLocal.begin() as db:
        row=db.scalar(select(ProxySync).where(ProxySync.source_id==source_id).with_for_update())
        current=db.get(ProxySource,source_id)
        if not row or not current or current.revision!=source_revision or row.revision!=revision:return
        row.checked_at=time.time();row.error=error
        if not error:row.inventory=[{'name':item['name'],'url':url_key(item['url'])} for item in inventory]
        row.revision=secrets.token_hex(16)


def run_due():
    with SessionLocal() as db:
        ids=list(db.scalars(select(ProxySync.source_id).where(ProxySync.enabled.is_(True),ProxySync.next_check<=time.time()).order_by(ProxySync.next_check).limit(2)))
    for source_id in ids:run_sync(source_id)
