from typing import Literal
from pydantic import BaseModel, ConfigDict, Field, HttpUrl, field_validator, model_validator

BASE_ITEMS = ['fastlink', 'tabs', 'weather', 'clock', 'theme', 'settings', 'logout', 'edit']
REQUIRED_ITEMS = {'settings', 'logout'}

class FooterLayout(BaseModel):
    model_config = ConfigDict(extra='forbid')
    order: list[str] = Field(max_length=40)
    hidden: list[str] = Field(default_factory=list, max_length=40)

    @model_validator(mode='after')
    def validate_items(self):
        if len(set(self.order)) != len(self.order) or len(set(self.hidden)) != len(self.hidden):
            raise ValueError('중복된 하단바 항목입니다.')
        if REQUIRED_ITEMS.intersection(self.hidden):
            raise ValueError('설정과 로그아웃은 숨길 수 없습니다.')
        if not REQUIRED_ITEMS.issubset(self.order):
            raise ValueError('설정과 로그아웃이 필요합니다.')
        return self

class MetricData(BaseModel):
    model_config = ConfigDict(extra='forbid', str_strip_whitespace=True)
    name: str = Field(min_length=1, max_length=60)
    provider: Literal['prometheus', 'grafana', 'kuma']
    base_url: HttpUrl = Field(max_length=2048)
    token: str | None = Field(default=None, min_length=1, max_length=4096)
    clear_token: bool = False
    query: str = Field(default='', max_length=2048)
    datasource_uid: str = Field(default='', max_length=128, pattern=r'^[a-zA-Z0-9_-]*$')
    slug: str = Field(default='default', max_length=128, pattern=r'^[a-zA-Z0-9_-]+$')
    monitor_id: str = Field(default='', max_length=20, pattern=r'^\d*$')
    metric: Literal['status', 'latency', 'uptime'] = 'status'
    display: Literal['value', 'sparkline', 'status'] = 'sparkline'
    unit: str = Field(default='', max_length=12)
    interval: int = Field(default=60, ge=60, le=86400)
    window: int = Field(default=3600, ge=300, le=86400)
    allow_private: bool = False
    enabled: bool = True
    audience: Literal['admin', 'all'] = 'admin'

    @field_validator('base_url')
    @classmethod
    def base(cls, value):
        if value.username or value.password or value.query or value.fragment:
            raise ValueError('인증 정보와 쿼리가 없는 서비스 기본 주소를 입력하세요.')
        # The IP is validated again and pinned at connection time.
        return value

    @field_validator('token')
    @classmethod
    def token_header(cls, value):
        if value is not None and any(ord(char) < 32 or ord(char) == 127 for char in value):
            raise ValueError('토큰에 제어 문자를 사용할 수 없습니다.')
        return value

    @model_validator(mode='after')
    def complete(self):
        if self.provider != 'kuma' and not self.query:
            raise ValueError('PromQL을 입력하세요. 하나의 시계열을 반환하도록 집계하세요.')
        if self.provider == 'grafana' and not self.datasource_uid:
            raise ValueError('Grafana의 Prometheus 데이터 소스 UID가 필요합니다.')
        if self.provider == 'kuma' and not self.monitor_id:
            raise ValueError('Uptime Kuma 모니터 ID가 필요합니다.')
        if self.provider != 'kuma' and self.display == 'status':
            raise ValueError('Prometheus 수치는 숫자 또는 그래프로 표시하세요.')
        if self.provider == 'kuma' and self.display == 'status' and self.metric != 'status':
            raise ValueError('상태 표시는 상태 지표를 선택하세요.')
        return self
