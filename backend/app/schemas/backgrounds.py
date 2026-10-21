from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, HttpUrl, field_validator

GifProvider = Literal['gifdb', 'pixabay', 'alphacoders', 'motionbgs', 'commons', 'openverse']
GifSearchProvider = Literal['all', 'gifdb', 'pixabay', 'alphacoders', 'motionbgs', 'commons', 'openverse']

class BackgroundSource(BaseModel):
    model_config = ConfigDict(extra='forbid')
    provider: GifProvider
    item_id: str = Field(min_length=1, max_length=160)
    title: str = Field(max_length=200)
    page_url: HttpUrl = Field(max_length=2048)
    author: str = Field(default='', max_length=300)
    license: str = Field(default='', max_length=80)
    license_url: HttpUrl | None = Field(default=None, max_length=2048)

    @field_validator('page_url', 'license_url')
    @classmethod
    def public_link(cls, value):
        if value and (value.scheme != 'https' or value.username or value.password):
            raise ValueError('HTTPS 출처 주소가 필요합니다.')
        return value


class BackgroundImport(BaseModel):
    model_config = ConfigDict(extra='forbid')
    provider: GifProvider
    item_id: str = Field(min_length=1, max_length=160)
