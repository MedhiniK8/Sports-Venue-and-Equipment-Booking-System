from pathlib import Path

import pytest
from pydantic import ValidationError

from app.config import Settings


def test_cors_origins_accept_json_and_legacy_csv_without_env_file():
    json_settings = Settings(
        _env_file=None,
        cors_origins='["http://localhost:5173","https://example.test"]',
    )
    csv_settings = Settings(
        _env_file=None,
        cors_origins="http://localhost:5173, https://example.test",
    )

    expected = ["http://localhost:5173", "https://example.test"]
    assert json_settings.cors_origins == expected
    assert csv_settings.cors_origins == expected


def test_env_example_cors_setting_uses_valid_json():
    example_file = Path(__file__).resolve().parents[3] / ".env.example"

    settings = Settings(_env_file=example_file)

    assert settings.cors_origins == [
        "http://localhost:5173",
        "http://127.0.0.1:5173",
    ]
    assert settings.jwt_secret_key.get_secret_value() == ""


def test_malformed_json_cors_origins_is_reported():
    with pytest.raises(ValidationError):
        Settings(_env_file=None, cors_origins='["http://localhost:5173"')


def test_database_url_requires_mysql_asyncmy_driver():
    with pytest.raises(ValidationError, match="mysql\\+asyncmy"):
        Settings(
            _env_file=None,
            database_url="sqlite+aiosqlite:///:memory:",
        )


def test_database_url_accepts_mysql_asyncmy():
    settings = Settings(
        _env_file=None,
        database_url="mysql+asyncmy://user:password@localhost:3306/booking",
    )

    assert settings.database_url.startswith("mysql+asyncmy://")
