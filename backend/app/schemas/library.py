from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, StringConstraints

from app.schemas.portal import IconColor, IconName


class SharedLinkData(BaseModel):
    model_config = ConfigDict(extra='forbid')
    name: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=120)]
    icon: IconName = 'world'
    icon_color: IconColor = 'auto'
    published: bool
    access_mode: Literal['all', 'restricted'] | None = None
    user_ids: list[int] | None = Field(default=None, max_length=1000)
    group_ids: list[str] | None = Field(default=None, max_length=200)


class AddSharedLink(BaseModel):
    model_config = ConfigDict(extra='forbid')
    category_id: str = Field(min_length=1, max_length=36)


class AddSharedLinks(AddSharedLink):
    link_ids: list[str] = Field(min_length=1, max_length=1000)
