import pytest

from app.config import Settings


def test_settings_read_from_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("APP_TIMEZONE", "Asia/Yekaterinburg")
    monkeypatch.setenv("SECRET_KEY", "s3cret")

    settings = Settings(_env_file=None)

    assert settings.app_timezone == "Asia/Yekaterinburg"
    assert settings.secret_key.get_secret_value() == "s3cret"
    assert "s3cret" not in repr(settings)


def test_unknown_app_env_is_rejected(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("APP_ENV", "staging")

    with pytest.raises(ValueError):
        Settings(_env_file=None)
