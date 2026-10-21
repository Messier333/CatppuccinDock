"""Admin-approved, pinned-address HTTP checks without user cookies or redirects."""
import http.client
import ipaddress
import socket
import ssl
import time
from concurrent.futures import ThreadPoolExecutor
from threading import BoundedSemaphore, RLock
from urllib.parse import urlsplit
from sqlalchemy import select
from app.db.models import ServiceMonitor
from app.db.session import SessionLocal

check_slots = BoundedSemaphore(4)
MAX_MONITORS = 1000
_queue_lock = RLock()
_executor = None
_jobs = {}


def secure_tls_context():
    context = ssl.create_default_context()
    context.minimum_version = ssl.TLSVersion.TLSv1_2
    return context


def pinned_http_connection():
    """Build an HTTP formatter whose destination comes only from its pinned socket."""
    return http.client.HTTPConnection('192.0.2.1', 1)


def start():
    global _executor
    with _queue_lock:
        if _executor is None:
            _executor = ThreadPoolExecutor(max_workers=4, thread_name_prefix='bookmark-check')


def stop():
    global _executor
    with _queue_lock:
        executor, _executor = _executor, None
    if executor:
        executor.shutdown(wait=True, cancel_futures=True)


def queue_checks(ids):
    """One bounded worker pool; identical requests share the same future."""
    start()
    accepted = {}
    with _queue_lock:
        for monitor_id in dict.fromkeys(ids):
            future = _jobs.get(monitor_id)
            if future is None:
                if len(_jobs) >= MAX_MONITORS:
                    continue
                future = _executor.submit(run_check, monitor_id)
                _jobs[monitor_id] = future
                def finished(done, key=monitor_id):
                    with _queue_lock:
                        if _jobs.get(key) is done:
                            _jobs.pop(key, None)
                future.add_done_callback(finished)
            accepted[monitor_id] = future
    return accepted


def safe_addresses(host, port, allow_private):
    try:
        addresses=list(dict.fromkeys(item[4][0] for item in socket.getaddrinfo(host,port,type=socket.SOCK_STREAM)))
    except (OSError,UnicodeError) as error:raise ValueError('DNS 조회 실패') from error
    if not addresses:raise ValueError('DNS 조회 실패')
    for value in addresses:
        address=ipaddress.ip_address(value)
        # Mapped IPv6 addresses must use the same policy as their IPv4 target.
        if getattr(address,'ipv4_mapped',None):address=address.ipv4_mapped
        if address.is_loopback or address.is_link_local or address.is_multicast or address.is_unspecified or address.is_reserved:
            raise ValueError('이 주소는 상태 확인 대상으로 허용되지 않습니다.')
        if not address.is_global and not (allow_private and (address.is_private or address in ipaddress.ip_network('100.64.0.0/10'))):
            raise ValueError('내부 주소 상태 확인을 허용해 주세요.')
    return addresses


def classify(status, location=''):
    if status in (401,403) or 300<=status<400 and any(part in urlsplit(location).path.lower() for part in ('login','signin','sign-in','oauth','oidc','authorize','authentication','/auth','/sso')):
        return 'up','응답 정상 · 인증 필요'
    if 200<=status<400:return 'up','정상 응답'
    return 'down','서비스 오류 응답'


def check_url(url, allow_private=False):
    parsed=urlsplit(url);host=parsed.hostname
    port=parsed.port or (443 if parsed.scheme=='https' else 80)
    sock=None;connection=None
    try:
        addresses=safe_addresses(host,port,allow_private)
        # Resolve once, validate all answers, and connect only to an approved IP.
        sock=socket.create_connection((addresses[0],port),timeout=3)
        if parsed.scheme=='https':sock=secure_tls_context().wrap_socket(sock,server_hostname=host)
        connection=pinned_http_connection();connection.sock=sock
        path=parsed.path or '/'
        if parsed.query:path+='?'+parsed.query
        host_header=('['+host+']' if ':' in host else host)+((':'+str(parsed.port)) if parsed.port else '')
        for method in ('HEAD','GET'):
            if method=='GET':
                connection.close()
                sock=socket.create_connection((addresses[0],port),timeout=3)
                if parsed.scheme=='https':sock=secure_tls_context().wrap_socket(sock,server_hostname=host)
                connection=pinned_http_connection();connection.sock=sock
            connection.putrequest(method,path,skip_host=True,skip_accept_encoding=True)
            connection.putheader('Host',host_header);connection.putheader('User-Agent','CatppuccinDock-Status/1.0');connection.putheader('Connection','close');connection.endheaders()
            response=connection.getresponse();status=response.status;location=response.getheader('Location','')
            if status not in (405,501) or method=='GET':
                state,detail=classify(status,location)
                return {'state':state,'http_status':status,'detail':detail}
        return {'state':'down','http_status':None,'detail':'응답을 확인하지 못했습니다.'}
    except ssl.SSLError:return {'state':'down','http_status':None,'detail':'TLS 인증서 또는 연결 확인 실패'}
    except ValueError as error:return {'state':'down','http_status':None,'detail':str(error)[:160]}
    except (OSError,http.client.HTTPException,UnicodeError):return {'state':'down','http_status':None,'detail':'연결 실패 또는 응답 시간 초과'}
    finally:
        if connection:connection.close()
        elif sock:sock.close()


def run_check(monitor_id,force=False):
    with SessionLocal.begin() as db:
        row=db.scalar(select(ServiceMonitor).where(ServiceMonitor.id==monitor_id).with_for_update())
        if not row or (not row.enabled and not force):return
        now = time.time()
        if row.checking_until > now:return
        expired = row.checking_until > 0
        if not force and not expired and row.next_check>now:return
        revision=row.revision;url=row.check_url;private=row.allow_private
        # A database lease also prevents duplicate probes across worker processes.
        lease = now + 60
        row.checking_until = lease
        row.next_check=now+max(row.interval,60)
    with check_slots:
        result=check_url(url,private)
    with SessionLocal.begin() as db:
        row=db.scalar(select(ServiceMonitor).where(ServiceMonitor.id==monitor_id).with_for_update())
        if not row or row.revision!=revision or row.checking_until != lease:return
        row.state=result['state'];row.http_status=result['http_status'];row.detail=result['detail'];row.checked_at=time.time()
        row.checking_until = 0
        row.next_check = row.checked_at + max(row.interval, 60)
        # Authentication responses are online; avoid repeatedly hitting login gates.
        if row.http_status in (401,403):row.next_check=time.time()+max(86400,row.interval)


def run_batch(ids):
    for future in queue_checks(ids).values():
        future.result()
