from typing import Literal
from urllib.parse import unquote, urlsplit

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class CustomAPI(BaseModel):
    model_config = ConfigDict(extra='forbid')
    endpoint: str = Field(min_length=1, max_length=1024)
    items_path: str = Field(default='', max_length=200, pattern=r'^(?:[\w-]+(?:\.[\w-]+)*)?$')
    url_field: str = Field(default='url', max_length=200, pattern=r'^(?:[\w-]+(?:\.[\w-]+)*)?$')
    name_field: str = Field(default='name', max_length=200, pattern=r'^(?:[\w-]+(?:\.[\w-]+)*)?$')
    url_format: Literal['url', 'domain'] = 'url'
    auth_type: Literal['bearer', 'header', 'none'] = 'bearer'
    auth_header: str = Field(default='X-API-Key', max_length=80, pattern=r'^(?:Authorization|X-[A-Za-z0-9-]+)$')

    @field_validator('endpoint')
    @classmethod
    def relative_endpoint(cls, value):
        value = value.strip()
        parsed = urlsplit(value)
        if not value.strip('/') or parsed.scheme or parsed.netloc or parsed.fragment or value.startswith('//') or '\\' in unquote(value) or '..' in unquote(parsed.path).split('/') or any(ord(char) < 33 for char in value):
            raise ValueError('같은 서비스 안의 API 경로를 입력하세요. 예: /api/links')
        return value.lstrip('/')


class SourceData(BaseModel):
    model_config = ConfigDict(extra='forbid')
    name: str = Field(min_length=1, max_length=80)
    provider: Literal['npm', 'npg', 'zoraxy', 'custom']
    base_url: str = Field(min_length=1, max_length=2048)
    token: str | None = Field(default=None, min_length=1, max_length=8192)
    verify_tls: bool = True
    custom_api: CustomAPI | None = None

    @model_validator(mode='after')
    def custom_configuration(self):
        if (self.provider == 'custom') != (self.custom_api is not None):
            raise ValueError('직접 등록하는 앱에는 API 경로와 응답 필드를 지정하세요.')
        return self

    @field_validator('name')
    @classmethod
    def trimmed_name(cls, value):
        if not value.strip():
            raise ValueError('연결 이름을 입력하세요.')
        return value.strip()

    @field_validator('base_url')
    @classmethod
    def url(cls, value):
        value = value.strip().rstrip('/')
        parsed = urlsplit(value)
        if parsed.scheme not in ('http', 'https') or not parsed.hostname or parsed.username or parsed.password or parsed.query or parsed.fragment:
            raise ValueError('관리 서비스의 HTTP/HTTPS 기본 주소를 입력하세요.')
        try:
            parsed.port
        except ValueError as error:
            raise ValueError('올바른 포트를 입력하세요.') from error
        return value

    @field_validator('token')
    @classmethod
    def token_value(cls, value):
        if value is not None and (not value.strip() or '\r' in value or '\n' in value):
            raise ValueError('유효한 API 토큰을 입력하세요.')
        return value.strip() if value is not None else None


class PreviewData(BaseModel):
    model_config = ConfigDict(extra='forbid')
    scheme: Literal['auto', 'http', 'https'] = 'auto'
    public_port: int | None = Field(default=None, ge=1, le=65535)


class ImportData(BaseModel):
    model_config = ConfigDict(extra='forbid')
    preview_id: str = Field(min_length=1, max_length=64)
    destination: Literal['private', 'library'] = 'private'
    category_id: str | None = Field(default=None, min_length=1, max_length=36)
    entry_ids: list[str] = Field(min_length=1, max_length=1000)

    @model_validator(mode='after')
    def category(self):
        if self.destination == 'private' and not self.category_id:
            raise ValueError('저장할 카테고리를 선택하세요.')
        return self
