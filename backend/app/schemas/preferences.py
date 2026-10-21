from typing import Literal
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError
from pydantic import BaseModel, ConfigDict, Field, field_validator


class PreferencesData(BaseModel):
    model_config = ConfigDict(extra='forbid', str_strip_whitespace=True)
    search_engine: Literal['g', 'd', 'p', 'y'] | None = None
    clock_format: Literal['12h', '24h'] | None = None
    timezone: str | None = Field(default=None, min_length=1, max_length=100)
    weather_location: str | None = Field(default=None, min_length=1, max_length=80)
    temperature_scale: Literal['C', 'F'] | None = None
    animation_mode: Literal['system', 'on', 'off'] | None = None

    @field_validator('timezone')
    @classmethod
    def valid_zone(cls, value):
        if value is not None:
            try: ZoneInfo(value)
            except (ValueError, ZoneInfoNotFoundError) as error: raise ValueError('올바른 시간대를 입력하세요.') from error
        return value
