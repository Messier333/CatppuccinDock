from typing import Annotated, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, HttpUrl, StringConstraints, model_validator


Name = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=80)]
IconName = Annotated[str, StringConstraints(max_length=64, pattern=r'^[a-z0-9-]+(?::[a-z0-9-]+)?$')]
IconColor = Annotated[str, StringConstraints(pattern=r'^(?:auto|#[a-fA-F0-9]{6})$')]


class TabData(BaseModel):
    model_config = ConfigDict(extra='forbid')
    name: Name
    banner: Literal['none', 'banner_11', 'banner_07', 'banner_15'] = 'none'
    background_id: UUID | None = None
    position: int = Field(default=0, ge=0, le=10000)


class CategoryData(BaseModel):
    model_config = ConfigDict(extra='forbid')
    tab_id: str
    name: Name
    position: int = Field(default=0, ge=0, le=10000)


class BookmarkData(BaseModel):
    model_config = ConfigDict(extra='forbid')
    category_id: str
    name: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=120)]
    url: HttpUrl = Field(max_length=2048)
    icon: IconName = 'world'
    icon_color: IconColor = 'auto'
    position: int = Field(default=0, ge=0, le=10000)


class ReorderData(BaseModel):
    model_config = ConfigDict(extra='forbid')
    kind: Literal['tabs', 'categories', 'bookmarks']
    parent_id: str | None = Field(default=None, min_length=1, max_length=36)
    ids: list[str] = Field(min_length=1, max_length=10000)

    @model_validator(mode='after')
    def unique_scope(self):
        if len(set(self.ids)) != len(self.ids) or any(not 1 <= len(value) <= 36 for value in self.ids):
            raise ValueError('중복 없이 올바른 항목을 지정하세요.')
        if self.kind != 'tabs' and not self.parent_id:
            raise ValueError('정렬할 탭 또는 카테고리를 지정하세요.')
        if self.kind == 'tabs' and self.parent_id:
            raise ValueError('탭 정렬에는 상위 항목을 지정하지 않습니다.')
        return self
