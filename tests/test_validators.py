"""Тесты валидаторов ФИО, телефона, населённого пункта."""

import pytest

from app.utils.validators import validate_city, validate_fio, validate_phone


@pytest.mark.parametrize(
    "raw,expected",
    [
        ("иванов иван иванович", "Иванов Иван Иванович"),
        ("  Петров   Пётр  ", "Петров Пётр"),
        ("СИДОРОВА АННА", "Сидорова Анна"),
        ("иванов-петров иван", "Иванов-Петров Иван"),
        ("о'нил джон", "О'Нил Джон"),
    ],
)
def test_fio_valid(raw, expected):
    res = validate_fio(raw)
    assert res.ok
    assert res.value == expected


@pytest.mark.parametrize(
    "raw",
    [
        "Иванов",  # одно слово
        "Ivanov Ivan",  # латиница
        "Иванов Иван Иванович Петрович",  # 4 слова
        "И И",  # слишком коротко
        "Иванов123 Иван",  # цифры
        "",
    ],
)
def test_fio_invalid(raw):
    assert not validate_fio(raw).ok


@pytest.mark.parametrize(
    "raw,expected",
    [
        ("89001234567", "+79001234567"),
        ("+7 (900) 123-45-67", "+79001234567"),
        ("79001234567", "+79001234567"),
        ("9001234567", "+79001234567"),
        ("+7 900 000-00-11", "+79000000011"),
    ],
)
def test_phone_valid(raw, expected):
    res = validate_phone(raw)
    assert res.ok
    assert res.value == expected


@pytest.mark.parametrize(
    "raw",
    ["12345", "+7 900 123", "abcdefghijk", "", "000000000000000"],
)
def test_phone_invalid(raw):
    assert not validate_phone(raw).ok


@pytest.mark.parametrize(
    "raw,expected",
    [
        ("г. Тверь", "г. Тверь"),
        ("п. Редкино", "п. Редкино"),
        ("  Ржев  ", "Ржев"),
        ("Западная Двина", "Западная Двина"),
    ],
)
def test_city_valid(raw, expected):
    res = validate_city(raw)
    assert res.ok
    assert res.value == expected


@pytest.mark.parametrize(
    "raw",
    ["Тверь123", "City", "1", "", "42"],
)
def test_city_invalid(raw):
    assert not validate_city(raw).ok
