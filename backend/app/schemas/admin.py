from typing import Literal
from urllib.parse import urlsplit
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class UserData(BaseModel):
    model_config = ConfigDict(extra='forbid')
    username: str = Field(min_length=1, max_length=64)
    role: Literal['admin', 'member'] = 'member'
    active: bool = True
    password: str | None = Field(default=None, min_length=12, max_length=256)

    @field_validator('username')
    @classmethod
    def name(cls, value):
        if not value.strip():
            raise ValueError('아이디를 입력하세요.')
        return value.strip()


class IdentityData(BaseModel):
    model_config = ConfigDict(extra='forbid')
    issuer: str = Field(min_length=1, max_length=1024)
    subject: str = Field(min_length=1, max_length=256)

    @field_validator('issuer')
    @classmethod
    def valid_issuer(cls, value):
        value = value.strip()
        parsed = urlsplit(value)
        if parsed.scheme not in ('https', 'http') or not parsed.netloc or parsed.query or parsed.fragment or parsed.username:
            raise ValueError('올바른 Issuer URL을 입력하세요.')
        return value


class UserCreate(UserData):
    login_type: Literal['local', 'oidc'] = 'local'
    oidc_subject: str | None = Field(default=None, min_length=1, max_length=256)

    @model_validator(mode='after')
    def login_method(self):
        if self.login_type == 'local' and not self.password:
            raise ValueError('일반 계정에는 비밀번호가 필요합니다.')
        if self.login_type == 'oidc':
            if self.password or not self.oidc_subject or not self.oidc_subject.strip():
                raise ValueError('OIDC 계정에는 비밀번호 대신 Subject를 입력하세요.')
            self.oidc_subject = self.oidc_subject.strip()
        elif self.oidc_subject is not None:
            raise ValueError('일반 계정에는 OIDC Subject를 지정할 수 없습니다.')
        return self


class OIDCSettings(BaseModel):
    model_config = ConfigDict(extra='forbid')
    enabled: bool = False
    login_mode: Literal['both', 'sso_only'] = 'both'
    label: str = Field(default='SSO', min_length=1, max_length=60)
    issuer: str = Field(default='', max_length=1024)
    client_id: str = Field(default='', max_length=256)
    client_secret: str | None = Field(default=None, min_length=1, max_length=4096)
    redirect_uri: str = Field(default='', max_length=2048)

    @field_validator('issuer', 'redirect_uri')
    @classmethod
    def url(cls, value):
        value = value.strip()
        if value:
            parsed = urlsplit(value)
            if parsed.scheme not in ('https', 'http') or not parsed.hostname or parsed.username or parsed.password or parsed.query or parsed.fragment:
                raise ValueError('올바른 HTTP/HTTPS 주소를 입력하세요.')
            try:
                parsed.port
            except ValueError as error:
                raise ValueError('포트가 올바르지 않습니다.') from error
        return value

    @field_validator('label', 'client_id')
    @classmethod
    def trimmed(cls, value):
        return value.strip()

    @model_validator(mode='after')
    def complete(self):
        if self.login_mode == 'sso_only' and not self.enabled:
            raise ValueError('SSO 전용 로그인에는 SSO 활성화가 필요합니다.')
        if not self.label:
            raise ValueError('로그인 버튼 이름을 입력하세요.')
        if self.enabled and not all((self.issuer, self.client_id, self.redirect_uri)):
            raise ValueError('OIDC 활성화에는 Issuer, Client ID, Callback URL이 필요합니다.')
        if self.redirect_uri and not self.redirect_uri.endswith('/api/auth/oidc/callback'):
            raise ValueError('Callback URL은 /api/auth/oidc/callback으로 끝나야 합니다.')
        return self


class PortalSettings(BaseModel):
    model_config = ConfigDict(extra='forbid')
    search_engine: Literal['d', 'g', 'p', 'y']
    search_open_mode: Literal['same_tab', 'new_tab'] = 'same_tab'
    clock_format: Literal['12h', '24h'] = '24h'
    timezone: str = Field(max_length=100)
    weather_location: str = Field(min_length=1, max_length=80)
    temperature_scale: Literal['C', 'F']
    tab_animation: bool = True
    bookmark_shelf_display: Literal['labels', 'icons'] = 'labels'

    @field_validator('timezone')
    @classmethod
    def zone(cls, value):
        try:
            ZoneInfo(value)
        except (ZoneInfoNotFoundError, ValueError) as error:
            raise ValueError('올바른 시간대를 입력하세요.') from error
        return value
