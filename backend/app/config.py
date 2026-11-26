import json
from functools import lru_cache
from typing import Annotated

from pydantic import Field, SecretStr, field_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict
from sqlalchemy.engine import make_url
from sqlalchemy.exc import ArgumentError


class Settings(BaseSettings):
    app_name: str = "Sports Venue and Equipment Booking System"
    environment: str = "development"
    cors_origins: Annotated[
        list[str],
        NoDecode,
    ] = ["http://localhost:5173", "http://127.0.0.1:5173"]
    database_url: str = "mysql+asyncmy://placeholder:placeholder@localhost:3306/placeholder"
    jwt_secret_key: SecretStr = SecretStr("")
    jwt_issuer: str = "sports-venue-booking"
    jwt_access_token_minutes: int = Field(default=30, gt=0)

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    @field_validator("cors_origins", mode="before")
    @classmethod
    def parse_cors_origins(cls, value: object) -> object:
        if not isinstance(value, str):
            return value

        value = value.strip()
        if value.startswith("["):
            try:
                parsed = json.loads(value)
            except json.JSONDecodeError as error:
                raise ValueError("CORS_ORIGINS must be a valid JSON string list") from error
        else:
            parsed = [origin.strip() for origin in value.split(",") if origin.strip()]

        if not isinstance(parsed, list) or not all(
            isinstance(origin, str) for origin in parsed
        ):
            raise ValueError("CORS_ORIGINS must be a JSON string list or CSV string")
        return parsed

    @field_validator("database_url")
    @classmethod
    def require_asyncmy_mysql_url(cls, value: str) -> str:
        try:
            parsed = make_url(value)
        except (ArgumentError, TypeError, ValueError) as error:
            raise ValueError(
                "DATABASE_URL must be a valid MySQL asyncmy URL"
            ) from error
        if (
            parsed.drivername != "mysql+asyncmy"
            or not parsed.host
            or not parsed.database
        ):
            raise ValueError(
                "DATABASE_URL must use mysql+asyncmy and include a host and database"
            )
        return value


@lru_cache
def get_settings() -> Settings:
    return Settings()
