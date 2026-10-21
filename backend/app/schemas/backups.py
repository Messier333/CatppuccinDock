from typing import Annotated, Literal
from pydantic import BaseModel, ConfigDict, Field, HttpUrl, StringConstraints, model_validator
from app.schemas.admin import PortalSettings
from app.schemas.portal import IconColor, IconName
from app.schemas.preferences import PreferencesData
from app.schemas.backgrounds import BackgroundSource

class Strict(BaseModel):
    model_config = ConfigDict(extra='forbid')

class SavedLink(Strict):
    name: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=120)]
    url: HttpUrl = Field(max_length=2048)
    icon: IconName = 'world'
    icon_color: IconColor = 'auto'
    favorite: bool = False
    shared_link_id: str | None = Field(default=None, max_length=36)

class SavedCategory(Strict):
    name: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=80)]
    links: list[SavedLink] = Field(default_factory=list, max_length=10000)

class SavedTab(Strict):
    name: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=80)]
    banner: Literal['none','banner_11','banner_07','banner_15'] = 'none'
    background_key: str | None = Field(default=None, max_length=64)
    categories: list[SavedCategory] = Field(default_factory=list, max_length=500)

class SavedImage(Strict):
    key: str = Field(min_length=1, max_length=64)
    name: str = Field(min_length=1, max_length=120)
    data: str = Field(max_length=14*1024*1024)
    source: BackgroundSource | None = None

class SavedIcon(Strict):
    key: IconName
    name: str = Field(min_length=1, max_length=120)
    data: str = Field(max_length=128*1024)

class BackupDocument(Strict):
    format: Literal['CatppuccinDock'] = 'CatppuccinDock'
    version: Literal[1] = 1
    created_at: str = Field(default='', max_length=80)
    tabs: list[SavedTab] = Field(min_length=1, max_length=100)
    images: list[SavedImage] = Field(default_factory=list, max_length=20)
    icons: list[SavedIcon] = Field(default_factory=list, max_length=100)
    settings: PortalSettings | None = None
    preferences: PreferencesData | None = None

    @model_validator(mode='after')
    def counts(self):
        if sum(len(tab.categories) for tab in self.tabs)>500 or sum(len(cat.links) for tab in self.tabs for cat in tab.categories)>10000:
            raise ValueError('최대 100개 탭, 500개 카테고리, 10,000개 북마크까지 가져올 수 있습니다.')
        keys = [image.key for image in self.images]
        if len(set(keys))!=len(keys) or any(tab.background_key and tab.background_key not in keys for tab in self.tabs):
            raise ValueError('GIF 참조 정보가 올바르지 않습니다.')
        icon_keys = [icon.key for icon in self.icons]
        if len(set(icon_keys)) != len(icon_keys) or any(not key.startswith('upload:') for key in icon_keys):
            raise ValueError('업로드 아이콘 참조 정보가 올바르지 않습니다.')
        if any(link.icon.startswith('upload:') and link.icon not in icon_keys for tab in self.tabs for cat in tab.categories for link in cat.links):
            raise ValueError('백업에 북마크의 업로드 아이콘 파일이 없습니다.')
        return self

class ExportData(Strict):
    encrypted: bool = False
    password: str = Field(default='', max_length=256)
    include_images: bool = True
    include_settings: bool = False

    @model_validator(mode='after')
    def encryption(self):
        if self.encrypted and len(self.password)<12:
            raise ValueError('암호화 비밀번호는 12자 이상 입력하세요.')
        if not self.encrypted and self.password:
            raise ValueError('비밀번호를 사용하려면 암호화를 선택하세요.')
        return self

class ImportApply(Strict):
    preview_id: str = Field(min_length=1, max_length=64)
    mode: Literal['merge','replace'] = 'merge'
    apply_settings: bool = False
    selected_ids: list[str] | None = Field(default=None, max_length=10000)
