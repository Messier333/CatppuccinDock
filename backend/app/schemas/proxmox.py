"""Finite UI and operation schemas; no caller-supplied API paths or methods."""
from typing import Literal
from pydantic import BaseModel, ConfigDict, Field, HttpUrl, field_validator, model_validator

METRICS = ['guests', 'nodes', 'cpu', 'memory', 'storage']
SECTIONS = ['overview', 'nodes', 'guests', 'storage', 'tasks']
COLUMNS = ['status', 'node', 'cpu', 'memory', 'disk', 'uptime']


class StrictModel(BaseModel):
    model_config = ConfigDict(extra='forbid', str_strip_whitespace=True)


class PanelSection(StrictModel):
    id: Literal['overview', 'nodes', 'guests', 'storage', 'tasks']
    visible: bool = True
    width: Literal['full', 'half'] = 'full'


class Presentation(StrictModel):
    bookmark_ids: list[str] = Field(default_factory=list, max_length=100)
    metrics: list[Literal['guests', 'nodes', 'cpu', 'memory', 'storage']] = Field(default_factory=lambda: ['guests'], max_length=3)
    sections: list[PanelSection] = Field(default_factory=lambda: [PanelSection(id=key) for key in SECTIONS], min_length=5, max_length=5)
    columns: list[Literal['status', 'node', 'cpu', 'memory', 'disk', 'uptime']] = Field(default_factory=lambda: ['status', 'node', 'cpu', 'memory'], max_length=6)

    @model_validator(mode='after')
    def unique(self):
        for values in (self.bookmark_ids, self.metrics, self.columns, [s.id for s in self.sections]):
            if len(values) != len(set(values)):
                raise ValueError('중복된 항목입니다.')
        if set(s.id for s in self.sections) != set(SECTIONS):
            raise ValueError('패널 구성이 올바르지 않습니다.')
        return self


class IntegrationData(Presentation):
    name: str = Field(min_length=1, max_length=80)
    base_url: HttpUrl = Field(max_length=2048)
    token_id: str = Field(min_length=5, max_length=256, pattern=r'^[A-Za-z0-9_.-]+@[A-Za-z0-9_.-]+![A-Za-z0-9_.-]+$')
    token: str | None = Field(default=None, min_length=1, max_length=1024)
    ca_certificate: str = Field(default='', max_length=32768)
    allow_private: bool = True
    enabled: bool = True
    controls: bool = False
    interval: int = Field(default=60, ge=30, le=3600)
    nodes: list[str] = Field(default_factory=list, max_length=128)

    @field_validator('base_url')
    @classmethod
    def base(cls, value):
        if value.scheme != 'https' or value.username or value.password or value.query or value.fragment or value.path not in ('', '/'):
            raise ValueError('Proxmox HTTPS 원본 주소를 입력하세요. 예: https://pve.example:8006')
        return value

    @field_validator('token')
    @classmethod
    def header(cls, value):
        if value is not None and any(ord(char) < 33 or ord(char) > 126 for char in value):
            raise ValueError('토큰 형식을 확인하세요.')
        return value

    @field_validator('nodes')
    @classmethod
    def node_names(cls, value):
        if len(value) != len(set(value)) or any(not name or len(name) > 128 or not all(c.isascii() and (c.isalnum() or c in '-_.') for c in name) for name in value):
            raise ValueError('노드 이름을 확인하세요.')
        return value


ActionName = Literal['start', 'shutdown', 'reboot', 'stop', 'reset', 'suspend', 'resume', 'snapshot', 'snapshot_delete', 'rollback', 'backup', 'clone', 'migrate', 'cpu', 'memory', 'onboot', 'template', 'delete', 'node_reboot', 'node_shutdown']


class ActionRequest(StrictModel):
    resource: str = Field(min_length=1, max_length=160)
    action: ActionName
    # Each action validates its own exact parameter set and value ranges.
    parameters: dict[str, str | int | bool] = Field(default_factory=dict, max_length=8)


class ExecuteRequest(StrictModel):
    intent: str = Field(min_length=32, max_length=64)
    confirmation: str = Field(min_length=1, max_length=160)
