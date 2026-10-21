import ipaddress
import logging
import os
import time
from logging.handlers import RotatingFileHandler
from pathlib import Path


logger = logging.getLogger('catppuccindock.security')


def configure_audit():
    for handler in list(logger.handlers):
        handler.close()
        logger.removeHandler(handler)
    formatter = logging.Formatter('%(asctime)s catppuccindock-auth %(message)s', datefmt='%Y-%m-%dT%H:%M:%SZ')
    formatter.converter = time.gmtime
    handlers = [logging.StreamHandler()]
    path = os.getenv('AUTH_LOG_PATH')
    if path:
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        handlers.append(RotatingFileHandler(path, maxBytes=5*1024*1024, backupCount=3, encoding='utf-8'))
    for handler in handlers:
        handler.setFormatter(formatter)
        logger.addHandler(handler)
    logger.setLevel(logging.INFO)
    logger.propagate = False


def client_address(request):
    # The backend is private; the frontend nginx overwrites X-Real-IP.
    value = request.headers.get('x-real-ip') or (request.client.host if request.client else 'unknown')
    try:
        return str(ipaddress.ip_address(value))
    except ValueError:
        return 'unknown'


def log_auth_failure(request, status):
    scope = request.url.path.rsplit('/', 1)[-1]
    logger.warning('failure client=%s scope=%s status=%s', client_address(request), scope, status)
