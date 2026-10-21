from pydantic import BaseModel, ConfigDict, Field


class Credentials(BaseModel):
    model_config = ConfigDict(extra='forbid')
    username: str = Field(min_length=1, max_length=64)
    password: str = Field(min_length=1, max_length=256)


class SetupCredentials(Credentials):
    password: str = Field(min_length=12, max_length=256)
    setup_code: str = Field(min_length=1, max_length=256)


class MFACode(BaseModel):
    code: str = Field(min_length=1, max_length=128)
