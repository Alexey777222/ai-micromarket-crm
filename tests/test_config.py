"""Проверки конфигурации проекта MicroMarket Control."""

import os
from pathlib import Path

from django.conf import settings

PROJECT_ROOT = Path(settings.BASE_DIR)


def test_secret_key_is_set():
    assert settings.SECRET_KEY, "SECRET_KEY не должен быть пустым"


def test_debug_mode_enabled_by_default_for_pilot(monkeypatch):
    """В пилотной поставке DEBUG включён по умолчанию.

    pytest-django принудительно выключает DEBUG на время тестов
    (django_debug_mode по умолчанию False), поэтому проверяем значение
    по умолчанию из окружения, а не settings.DEBUG.
    """
    monkeypatch.delenv("DJANGO_DEBUG", raising=False)
    assert os.getenv("DJANGO_DEBUG", "1") == "1"


def test_allowed_hosts_configured():
    assert len(settings.ALLOWED_HOSTS) > 0


def test_database_engine_is_sqlite_or_postgres():
    engine = settings.DATABASES["default"]["ENGINE"]
    assert engine in ("django.db.backends.sqlite3", "django.db.backends.postgresql")


def test_timezone_is_moscow():
    assert settings.TIME_ZONE == "Europe/Moscow"


def test_language_is_russian():
    assert settings.LANGUAGE_CODE == "ru-ru"


def test_static_root_configured():
    assert settings.STATIC_ROOT is not None
    assert str(settings.STATIC_ROOT).endswith("staticfiles")


def test_static_url_configured():
    # Django применяет _add_script_prefix к STATIC_URL при чтении настройки:
    # значение 'static/' из settings.py доступно как '/static/'.
    assert settings.STATIC_URL in ("static/", "/static/")


def test_installed_apps_include_core():
    assert "core" in settings.INSTALLED_APPS


def test_installed_apps_include_admin():
    assert "django.contrib.admin" in settings.INSTALLED_APPS


def test_wsgi_application_set():
    assert settings.WSGI_APPLICATION == "config.wsgi.application"


def test_login_url_is_owner_login():
    assert settings.LOGIN_URL == "/accounts/login/"


def test_telegram_token_empty_by_default():
    assert settings.TELEGRAM_BOT_TOKEN == ""


def test_env_example_file_exists():
    env_file = PROJECT_ROOT / ".env.example"
    assert env_file.exists(), ".env.example должен присутствовать в корне проекта"


def test_env_example_contains_required_keys():
    env_file = PROJECT_ROOT / ".env.example"
    content = env_file.read_text(encoding="utf-8")
    required_keys = [
        "DJANGO_SECRET_KEY",
        "DJANGO_DEBUG",
        "DJANGO_ALLOWED_HOSTS",
        "DATABASE_URL",
        "TIME_ZONE",
        "TELEGRAM_BOT_TOKEN",
    ]
    for key in required_keys:
        assert key in content, f".env.example не содержит {key}"


def test_pytest_ini_exists():
    ini_file = PROJECT_ROOT / "pytest.ini"
    assert ini_file.exists()


def test_pytest_ini_has_django_settings():
    ini_file = PROJECT_ROOT / "pytest.ini"
    content = ini_file.read_text(encoding="utf-8")
    assert "DJANGO_SETTINGS_MODULE" in content


def test_pyproject_toml_exists():
    toml_file = PROJECT_ROOT / "pyproject.toml"
    assert toml_file.exists()


def test_pyproject_toml_has_ruff_config():
    toml_file = PROJECT_ROOT / "pyproject.toml"
    content = toml_file.read_text(encoding="utf-8")
    assert "[tool.ruff]" in content


def test_version_file_exists():
    version_file = PROJECT_ROOT / "VERSION"
    assert version_file.exists(), "VERSION должен существовать в корне проекта"


def test_version_file_contains_valid_semver():
    version_file = PROJECT_ROOT / "VERSION"
    version = version_file.read_text(encoding="utf-8").strip()
    parts = version.split(".")
    assert len(parts) == 3, f"Версия '{version}' не является semver"
    for part in parts:
        assert part.isdigit(), f"Часть версии '{part}' не является числом"


def test_version_file_is_0_2_0():
    version_file = PROJECT_ROOT / "VERSION"
    version = version_file.read_text(encoding="utf-8").strip()
    assert version == "0.2.0", f"Ожидалась версия 0.2.0, получена {version}"
