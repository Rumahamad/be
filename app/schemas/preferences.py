from typing import Literal

from pydantic import BaseModel

LanguageCode = Literal["en", "bn", "ur"]
ThemeCode = Literal["bnc-green", "night"]


class PreferencesOutput(BaseModel):
    language: LanguageCode
    theme: ThemeCode
    is_rtl: bool


class UpdatePreferencesInput(BaseModel):
    language: LanguageCode | None = None
    theme: ThemeCode | None = None
