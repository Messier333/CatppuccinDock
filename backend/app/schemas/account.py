from pydantic import BaseModel, Field


class Reauthentication(BaseModel):
    password: str = Field(default='', max_length=256)
    code: str = Field(default='', max_length=128)


class NewPassword(BaseModel):
    current_password: str = Field(min_length=1, max_length=256)
    new_password: str = Field(min_length=12, max_length=256)


class ConfirmTOTP(BaseModel):
    code: str = Field(pattern=r'^\d{6}$')
