import secrets,time
from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException
from pydantic import BaseModel, ConfigDict, Field, HttpUrl, ValidationError, field_validator
from sqlalchemy import delete, select
from app.api.dependencies import require_admin, require_mutation_header, require_user
from app.db.models import Bookmark, ServiceMonitor, User
from app.db.session import SessionLocal
from app.services.library import allowed_link_ids, shared_links_for_bookmarks
from app.services.monitoring import MAX_MONITORS, queue_checks, run_check, run_batch
from app.services.proxy import url_key

router=APIRouter(prefix='/api')

class MonitorData(BaseModel):
    model_config=ConfigDict(extra='forbid',str_strip_whitespace=True)
    name:str=Field(min_length=1,max_length=120)
    link_url:HttpUrl=Field(max_length=2048)
    check_url:HttpUrl=Field(max_length=2048)
    allow_private:bool=False
    enabled:bool=True
    interval:int=Field(default=300,ge=60,le=86400)
    @field_validator('link_url','check_url')
    @classmethod
    def no_credentials(cls,value):
        if value.username or value.password:raise ValueError('인증 정보가 없는 주소를 입력하세요.')
        return value

class BulkMonitorData(BaseModel):
    model_config=ConfigDict(extra='forbid')
    bookmark_ids:list[str]=Field(min_length=1,max_length=200)
    allow_private:bool=False
    interval:int=Field(default=300,ge=60,le=86400)

class VisibleStatusData(BaseModel):
    model_config=ConfigDict(extra='forbid')
    bookmark_ids:list[str]=Field(min_length=1,max_length=200)

def representation(row):
    result={key:getattr(row,key) for key in ('id','name','link_url','check_url','allow_private','enabled','interval','state','http_status','detail','checked_at','next_check')}
    if result['state']=='auth':result['state']='up'
    return result

@router.get('/admin/monitors',dependencies=[Depends(require_admin)])
def monitors():
    with SessionLocal() as db:return [representation(row) for row in db.scalars(select(ServiceMonitor).order_by(ServiceMonitor.name))]

def save(db,payload,monitor_id=None):
    from app.db.models import Setting
    db.scalar(select(Setting).where(Setting.key=='portal').with_for_update())
    row=db.get(ServiceMonitor,monitor_id) if monitor_id else ServiceMonitor()
    if not row:raise HTTPException(404,'상태 확인 대상을 찾을 수 없습니다.')
    from sqlalchemy import func
    if not monitor_id and db.scalar(select(func.count()).select_from(ServiceMonitor))>=MAX_MONITORS:raise HTTPException(409,f'상태 확인 대상은 최대 {MAX_MONITORS}개입니다.')
    duplicate=db.scalar(select(ServiceMonitor).where(ServiceMonitor.link_url==str(payload.link_url)))
    if duplicate and duplicate.id!=row.id:raise HTTPException(409,'이미 등록한 북마크 주소입니다.')
    for key,value in payload.model_dump(mode='json').items():setattr(row,key,value)
    row.revision=secrets.token_hex(16);row.next_check=0;row.checking_until=0;row.state='pending';row.checked_at=None;row.http_status=None;row.detail=''
    db.add(row);db.flush();return representation(row)

@router.post('/admin/monitors',dependencies=[Depends(require_admin),Depends(require_mutation_header)])
def create(payload:MonitorData):
    with SessionLocal.begin() as db:return save(db,payload)

@router.post('/admin/monitors/bulk',dependencies=[Depends(require_mutation_header)])
def create_bulk(payload:BulkMonitorData,user:User=Depends(require_admin)):
    from app.db.models import Setting
    with SessionLocal.begin() as db:
        db.scalar(select(Setting).where(Setting.key=='portal').with_for_update())
        db.scalar(select(User).where(User.id==user.id).with_for_update())
        ids=list(dict.fromkeys(payload.bookmark_ids))
        bookmarks={row.id:row for row in db.scalars(select(Bookmark).where(Bookmark.user_id==user.id,Bookmark.id.in_(ids)))}
        if set(bookmarks)!=set(ids):raise HTTPException(409,'북마크 목록이 변경됐습니다. 다시 불러온 뒤 선택해 주세요.')
        shared=shared_links_for_bookmarks(db,ids)
        allowed=allowed_link_ids(db,user)
        existing=list(db.scalars(select(ServiceMonitor)))
        seen={url_key(row.link_url) for row in existing}
        pending=[]
        duplicates=len(payload.bookmark_ids)-len(ids)
        for bookmark_id in ids:
            bookmark=bookmarks[bookmark_id]
            managed=shared.get(bookmark_id)
            if managed and managed.id not in allowed:raise HTTPException(409,'공개 링크 권한이 변경됐습니다. 다시 불러온 뒤 선택해 주세요.')
            url=url_key(managed.url if managed else bookmark.url)
            if url in seen:
                duplicates+=1
                continue
            try:
                config=MonitorData(name=bookmark.name,link_url=url,check_url=url,allow_private=payload.allow_private,interval=payload.interval)
            except ValidationError as error:
                raise HTTPException(422,'선택한 북마크 주소를 확인해 주세요. HTTP/HTTPS 주소여야 하며 주소에 인증 정보가 포함되면 안 됩니다.') from error
            pending.append(config)
            seen.add(url)
        if len(existing)+len(pending)>MAX_MONITORS:raise HTTPException(409,f'상태 확인 대상은 최대 {MAX_MONITORS}개입니다. 선택 개수를 줄여 주세요.')
        for config in pending:
            db.add(ServiceMonitor(**config.model_dump(mode='json'),revision=secrets.token_hex(16),next_check=0,state='pending'))
        return {'added':len(pending),'duplicates':duplicates}

@router.put('/admin/monitors/{monitor_id}',dependencies=[Depends(require_admin),Depends(require_mutation_header)])
def update(monitor_id:str,payload:MonitorData):
    with SessionLocal.begin() as db:return save(db,payload,monitor_id)

@router.post('/admin/monitors/check-all',dependencies=[Depends(require_admin),Depends(require_mutation_header)])
def check_all(tasks:BackgroundTasks):
    from app.db.models import Setting
    with SessionLocal.begin() as db:
        db.scalar(select(Setting).where(Setting.key=='portal').with_for_update())
        now=time.time()
        last=db.get(Setting,'monitor-check-all')
        if last and last.value.get('requested_at',0)>now-15:raise HTTPException(409,'전체 확인은 15초 후 다시 요청해 주세요.')
        rows=list(db.scalars(select(ServiceMonitor).where(ServiceMonitor.enabled.is_(True)).order_by(ServiceMonitor.id).with_for_update()))
        ids=[]
        for row in rows:
            if row.checked_at and row.checked_at>now-15:continue
            row.next_check=0
            ids.append(row.id)
        if ids:
            if last:last.value={'requested_at':now}
            else:db.add(Setting(key='monitor-check-all',value={'requested_at':now}))
    if ids:tasks.add_task(run_batch,ids)
    return {'queued_ids':ids,'skipped':len(rows)-len(ids),'requested_at':now}

@router.delete('/admin/monitors/{monitor_id}',dependencies=[Depends(require_admin),Depends(require_mutation_header)])
def remove(monitor_id:str):
    with SessionLocal.begin() as db:db.execute(delete(ServiceMonitor).where(ServiceMonitor.id==monitor_id))
    return {'ok':True}

@router.post('/admin/monitors/{monitor_id}/check',dependencies=[Depends(require_admin),Depends(require_mutation_header)])
def check(monitor_id:str):
    with SessionLocal() as db:
        row=db.get(ServiceMonitor,monitor_id)
        if not row:raise HTTPException(404,'상태 확인 대상을 찾을 수 없습니다.')
        if row.checked_at and row.checked_at>time.time()-15:raise HTTPException(409,'잠시 후 다시 확인해 주세요.')
    run_check(monitor_id,force=True)
    with SessionLocal() as db:return representation(db.get(ServiceMonitor,monitor_id))

def bookmark_monitors(db,user,ids=None):
    statement=select(Bookmark).where(Bookmark.user_id==user.id)
    if ids is not None:statement=statement.where(Bookmark.id.in_(ids))
    bookmarks=list(db.scalars(statement))
    shared=shared_links_for_bookmarks(db,[row.id for row in bookmarks])
    allowed=allowed_link_ids(db,user) if shared else set()
    urls={}
    for row in bookmarks:
        managed=shared.get(row.id)
        if managed and managed.id not in allowed:continue
        urls[row.id]=managed.url if managed else row.url
    candidates=set(urls.values()) | {url_key(url) for url in urls.values()}
    monitors={url_key(row.link_url):row for row in db.scalars(select(ServiceMonitor).where(ServiceMonitor.enabled.is_(True),ServiceMonitor.link_url.in_(candidates)))}
    return {bid:monitors[url_key(url)] for bid,url in urls.items() if url_key(url) in monitors}


def cached_status(row,now):
    return {'state':'up' if row.state=='auth' else row.state,'checked_at':row.checked_at,
            'detail':row.detail or ('상태 확인 대기 중' if row.checked_at is None else ''),
            'refreshing':row.checking_until>now}


@router.get('/bookmark-status')
def bookmark_status(user:User=Depends(require_user)):
    with SessionLocal() as db:
        return {bid:cached_status(row,time.time()) for bid,row in bookmark_monitors(db,user).items()}


@router.post('/bookmark-status/refresh',dependencies=[Depends(require_mutation_header)])
def refresh_visible(payload:VisibleStatusData,user:User=Depends(require_user)):
    now=time.time()
    with SessionLocal() as db:
        mapped=bookmark_monitors(db,user,set(payload.bookmark_ids))
        statuses={bid:cached_status(row,now) for bid,row in mapped.items()}
        # The interval is a shared cache freshness limit; hidden links never trigger I/O.
        due={row.id for row in mapped.values() if row.checking_until<=now and (row.next_check<=now or row.checking_until>0)}
        running=any(row.checking_until>now for row in mapped.values())
    queued=queue_checks(due) if due else {}
    return {'statuses':statuses,'refreshing':bool(queued) or running}
