"""Конфигурация приложения (pydantic-settings)."""

from __future__ import annotations

from functools import lru_cache
from typing import Annotated

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict


class Settings(BaseSettings):
    """Все настройки читаются из окружения / .env."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

    # --- MAX Bot API ---
    bot_token: str = Field(default="", alias="BOT_TOKEN")
    api_base_url: str = Field(
        default="https://platform-api2.max.ru", alias="API_BASE_URL"
    )

    mode: str = Field(default="polling", alias="MODE")  # webhook | polling
    webhook_url: str = Field(default="", alias="WEBHOOK_URL")
    webhook_secret: str = Field(default="", alias="WEBHOOK_SECRET")
    webhook_path: str = Field(default="/max/webhook", alias="WEBHOOK_PATH")
    web_host: str = Field(default="0.0.0.0", alias="WEB_HOST")
    web_port: int = Field(default=8080, alias="WEB_PORT")

    # --- Хранилища ---
    database_url: str = Field(
        default="sqlite+aiosqlite:///./data/bot.db", alias="DATABASE_URL"
    )
    redis_url: str = Field(default="", alias="REDIS_URL")

    # --- Доступ ---
    # NoDecode: без него pydantic-settings разбирает значение сложного типа
    # (list) как JSON ещё до валидатора и падает на "ADMIN_USER_IDS=" —
    # пустая строка не является валидным JSON.
    admin_user_ids: Annotated[list[int], NoDecode] = Field(
        default_factory=list, alias="ADMIN_USER_IDS"
    )

    admin_chat_default_id: int | None = Field(default=None, alias="ADMIN_CHAT_DEFAULT_ID")
    admin_chat_join_id: int | None = Field(default=None, alias="ADMIN_CHAT_JOIN_ID")
    admin_chat_job_id: int | None = Field(default=None, alias="ADMIN_CHAT_JOB_ID")
    admin_chat_psy_id: int | None = Field(default=None, alias="ADMIN_CHAT_PSY_ID")
    admin_chat_law_id: int | None = Field(default=None, alias="ADMIN_CHAT_LAW_ID")
    admin_chat_other_id: int | None = Field(default=None, alias="ADMIN_CHAT_OTHER_ID")

    # --- Контакты организации ---
    org_phone: str = Field(default="", alias="ORG_PHONE")
    org_email: str = Field(default="", alias="ORG_EMAIL")
    org_site_url: str = Field(default="", alias="ORG_SITE_URL")
    privacy_policy_url: str = Field(default="", alias="PRIVACY_POLICY_URL")

    # --- Поведение ---
    consent_version: str = Field(default="1.0", alias="CONSENT_VERSION")
    duplicate_window_hours: int = Field(default=24, alias="DUPLICATE_WINDOW_HOURS")
    ask_free_text_for_other: bool = Field(default=False, alias="ASK_FREE_TEXT_FOR_OTHER")
    response_sla_days: int = Field(default=3, alias="RESPONSE_SLA_DAYS")

    # --- Инфраструктура ---
    log_level: str = Field(default="INFO", alias="LOG_LEVEL")
    tz: str = Field(default="Europe/Moscow", alias="TZ")
    backup_dir: str = Field(default="./backups", alias="BACKUP_DIR")
    backup_retention_days: int = Field(default=30, alias="BACKUP_RETENTION_DAYS")

    @field_validator("admin_user_ids", mode="before")
    @classmethod
    def _parse_admin_ids(cls, value: object) -> list[int]:
        """Принимает "1,2,3", список, None и пустую строку.

        Некорректные элементы игнорируются: опечатка в .env не должна
        приводить к падению бота при старте.
        """
        if value is None:
            return []
        items: list[object]
        if isinstance(value, str):
            # Терпим и "1,2", и JSON-подобное "[1, 2]" — иначе admin молча
            # потерял бы доступ из-за формата записи.
            text = value.strip().strip("[]")
            items = [x.strip() for x in text.split(",")]
        elif isinstance(value, (list, tuple, set)):
            items = list(value)
        else:
            items = [value]

        result: list[int] = []
        for item in items:
            text = str(item).strip().strip("\"'")
            if not text:
                continue
            try:
                result.append(int(text))
            except ValueError:
                continue
        return result

    @field_validator(
        "admin_chat_default_id",
        "admin_chat_join_id",
        "admin_chat_job_id",
        "admin_chat_psy_id",
        "admin_chat_law_id",
        "admin_chat_other_id",
        mode="before",
    )
    @classmethod
    def _empty_to_none(cls, value: object) -> object:
        if value is None or (isinstance(value, str) and not value.strip()):
            return None
        return value

    @property
    def use_webhook(self) -> bool:
        return self.mode.strip().lower() == "webhook"

    @property
    def use_redis(self) -> bool:
        return bool(self.redis_url.strip())

    def is_admin(self, user_id: int | None) -> bool:
        return user_id is not None and user_id in self.admin_user_ids

    def admin_chat_for(self, kind: str, direction: str | None = None) -> int | None:
        """Возвращает chat_id оператора для заявки.

        kind: 'join' | 'consult'. direction: job|psy|law|other (для консультаций).
        Фолбэк на ADMIN_CHAT_DEFAULT_ID.
        """
        specific: int | None = None
        if kind == "join":
            specific = self.admin_chat_join_id
        elif kind == "consult":
            specific = {
                "job": self.admin_chat_job_id,
                "psy": self.admin_chat_psy_id,
                "law": self.admin_chat_law_id,
                "other": self.admin_chat_other_id,
            }.get(direction or "")
        return specific if specific is not None else self.admin_chat_default_id


@lru_cache
def get_settings() -> Settings:
    return Settings()
