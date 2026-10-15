"""Reusable validated field types. Every request model forbids unknown fields."""

import re
import unicodedata
from typing import Annotated

from pydantic import AfterValidator, BaseModel, ConfigDict, StringConstraints


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


_CONTROL = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f​-‏‪-‮⁦-⁩]")
_EMAIL = re.compile(r"^[a-z0-9._%+\-]{1,64}@[a-z0-9.\-]{1,253}\.[a-z]{2,24}$")


def _single_line(value: str) -> str:
    value = unicodedata.normalize("NFC", value)
    if _CONTROL.search(value) or "\n" in value or "\r" in value:
        raise ValueError("contains control or invisible characters")
    return value


def _multi_line(value: str) -> str:
    value = unicodedata.normalize("NFC", value).replace("\r\n", "\n")
    if _CONTROL.search(value) or "\r" in value:
        raise ValueError("contains control or invisible characters")
    return value


def _person_name(value: str) -> str:
    """Latin-script letters plus common punctuation: keeps names unambiguous (no homoglyph mixing)."""
    value = _single_line(value)
    for ch in value:
        if ch.isalpha():
            if not unicodedata.name(ch, "").startswith("LATIN"):
                raise ValueError("use Latin letters only")
        elif ch not in " -'.":
            raise ValueError("contains characters that are not allowed in a name")
    if not any(ch.isalpha() for ch in value):
        raise ValueError("must contain letters")
    return re.sub(r"\s+", " ", value)


def _email(value: str) -> str:
    value = value.strip().lower()
    if not _EMAIL.match(value) or ".." in value:
        raise ValueError("is not a valid e-mail address")
    return value


def _phone(value: str) -> str:
    value = _single_line(value)
    if value and not re.fullmatch(r"\+?[0-9 ()\-]{6,24}", value):
        raise ValueError("is not a valid phone number")
    return value


ShortText = Annotated[str, StringConstraints(min_length=1, max_length=200), AfterValidator(_single_line)]
OptionalShortText = Annotated[str, StringConstraints(max_length=200), AfterValidator(_single_line)]
LongText = Annotated[str, StringConstraints(min_length=1, max_length=4000), AfterValidator(_multi_line)]
Reason = Annotated[str, StringConstraints(min_length=15, max_length=500), AfterValidator(_multi_line)]
PersonName = Annotated[str, StringConstraints(min_length=2, max_length=120), AfterValidator(_person_name)]
Email = Annotated[str, StringConstraints(min_length=3, max_length=254), AfterValidator(_email)]
Phone = Annotated[str, StringConstraints(max_length=24), AfterValidator(_phone)]
Password = Annotated[str, StringConstraints(min_length=1, max_length=128)]
BedId = Annotated[str, StringConstraints(pattern=r"^B\d{2}$")]
MonitorId = Annotated[str, StringConstraints(pattern=r"^MON-\d{2}$")]
