from pydantic import BaseModel, ConfigDict, Field


class MediaPolicy(BaseModel):
    model_config = ConfigDict(extra='forbid')
    member_import: bool = True
    member_upload: bool = True
    member_per_minute: int = Field(default=1, ge=1, le=10)
    member_per_day: int = Field(default=5, ge=1, le=100)
    member_daily_mb: int = Field(default=200, ge=1, le=2000)
    member_storage_mb: int = Field(default=200, ge=10, le=200)
    server_per_day: int = Field(default=100, ge=1, le=5000)
    server_daily_mb: int = Field(default=2048, ge=1, le=50000)
    server_storage_mb: int = Field(default=2048, ge=10, le=100000)


class MediaSettings(MediaPolicy):
    pixabay_key: str | None = Field(default=None, max_length=256)
    clear_pixabay_key: bool = False
