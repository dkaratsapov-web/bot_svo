"""Валидация и нормализация пользовательского ввода."""

from __future__ import annotations

import re
from dataclasses import dataclass

# ФИО: только кириллица (в т.ч. Ё/ё), дефис и апостроф внутри слов
_FIO_WORD = r"[А-ЯЁа-яё]+(?:[-'][А-ЯЁа-яё]+)*"
_FIO_RE = re.compile(rf"^{_FIO_WORD}(?:\s+{_FIO_WORD}){{1,2}}$")

# Населённый пункт: кириллица + пробел, дефис, точка. Цифры запрещены.
_CITY_RE = re.compile(r"^[А-ЯЁа-яё .\-]+$")


@dataclass(slots=True)
class Result:
    ok: bool
    value: str | None = None
    error: str | None = None


# --------------------------------------------------------------------------- #
# ФИО
# --------------------------------------------------------------------------- #
def _title_case_ru(word: str) -> str:
    """Title Case с сохранением дефисов/апострофов (Иванов-Петров, О'Ливье)."""

    def cap(chunk: str) -> str:
        return chunk[:1].upper() + chunk[1:].lower() if chunk else chunk

    for sep in ("-", "'"):
        if sep in word:
            return sep.join(_title_case_ru(p) for p in word.split(sep))
    return cap(word)


def validate_fio(raw: str) -> Result:
    """2–3 слова, только кириллица/дефис/апостроф, длина 5–120, Title Case."""
    if raw is None:
        return Result(False, error="empty")
    text = re.sub(r"\s+", " ", raw.strip())
    if not (5 <= len(text) <= 120):
        return Result(False, error="length")
    if not _FIO_RE.match(text):
        return Result(False, error="format")
    normalized = " ".join(_title_case_ru(w) for w in text.split(" "))
    return Result(True, value=normalized)


# --------------------------------------------------------------------------- #
# Телефон
# --------------------------------------------------------------------------- #
def validate_phone(raw: str) -> Result:
    """Нормализует к +7XXXXXXXXXX. Принимает 8XXXXXXXXXX, 7XXXXXXXXXX, +7 (…) …."""
    if raw is None:
        return Result(False, error="empty")
    digits = re.sub(r"\D", "", raw)

    if len(digits) == 11 and digits[0] in ("7", "8"):
        core = digits[1:]
    elif len(digits) == 10:
        core = digits
    else:
        return Result(False, error="length")

    # Российский мобильный/городской: первая цифра значащей части 3..9
    if core[0] == "0":
        return Result(False, error="format")

    return Result(True, value=f"+7{core}")


# --------------------------------------------------------------------------- #
# Населённый пункт
# --------------------------------------------------------------------------- #
def validate_city(raw: str) -> Result:
    """2–80 символов, кириллица + пробел/дефис/точка, без цифр."""
    if raw is None:
        return Result(False, error="empty")
    text = re.sub(r"\s+", " ", raw.strip())
    if not (2 <= len(text) <= 80):
        return Result(False, error="length")
    if not _CITY_RE.match(text):
        return Result(False, error="format")
    if not any(ch.isalpha() for ch in text):
        return Result(False, error="format")
    return Result(True, value=text)
