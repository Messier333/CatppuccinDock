from typing import Literal
from pydantic import BaseModel, ConfigDict, Field, HttpUrl, field_validator, model_validator
from app.schemas.portal import IconColor, IconName


class PreviewData(BaseModel):
    model_config = ConfigDict(extra='forbid')
    url: HttpUrl = Field(max_length=2048)

    @field_validator('url')
    @classmethod
    def no_credentials(cls,value):
        if value.username or value.password: raise ValueError('주소에 아이디·비밀번호를 포함할 수 없습니다.')
        return value


class FavoriteData(BaseModel):
    model_config = ConfigDict(extra='forbid')
    favorite: bool


class BulkData(BaseModel):
    model_config = ConfigDict(extra='forbid')
    ids: list[str] = Field(min_length=1,max_length=500)
    action: Literal['move','icon','delete']
    category_id: str | None = Field(default=None,min_length=1,max_length=36)
    icon: IconName | None = None
    icon_color: IconColor = 'auto'

    @model_validator(mode='after')
    def scope(self):
        if len(self.ids)!=len(set(self.ids)) or any(not 1<=len(value)<=36 for value in self.ids): raise ValueError('중복 없이 북마크를 선택하세요.')
        if self.action=='move' and not self.category_id: raise ValueError('이동할 카테고리를 선택하세요.')
        if self.action=='icon' and not self.icon: raise ValueError('아이콘을 선택하세요.')
        return self
