import importlib.util
import os
import subprocess
import sys
from io import StringIO
from pathlib import Path
from unittest.mock import patch

import pytest
from django.contrib.auth.models import User
from django.core.management import call_command
from django.core.management.base import CommandError
from django.db import DatabaseError
from django.test import Client, override_settings

from core.models import Membership, Organization, Product

ROOT = Path(__file__).resolve().parent.parent
SCREENS = ["fridges", "products", "stock", "batches", "sales", "writeoffs", "forecasts"]


@pytest.fixture(autouse=True)
def isolated_server_database(db):
    # Legacy business-demo tests leave a session-scoped dataset behind.
    # Flush ONLY pytest's test DB, inside its per-test rollback transaction.
    call_command("flush", interactive=False, verbosity=0)


@pytest.fixture
def owner(db):
    user = User.objects.create_user("owner", password="fixture-password")
    org = Organization.objects.create(name="Test owner's organization")
    Membership.objects.create(user=user, organization=org, role=Membership.Role.OWNER)
    return user, org


@pytest.mark.parametrize("screen", SCREENS)
def test_anonymous_cannot_see_records(client, screen):
    response = client.get(f"/records/{screen}/")
    assert response.status_code == 302
    assert response.url.startswith("/accounts/login/")


@pytest.mark.parametrize("screen", SCREENS)
def test_owner_screens_open(client, owner, screen):
    client.force_login(owner[0])
    response = client.get(f"/records/{screen}/")
    assert response.status_code == 200
    assert "no-store" in response["Cache-Control"]
    assert "noindex" in response["X-Robots-Tag"]


def test_product_organization_isolation_and_pagination(client, owner):
    user, org = owner
    other = Organization.objects.create(name="Other organization")
    Product.objects.create(organization=other, sku="SECRET", name="PRIVATE_PRODUCT", cost_price=1, sale_price=2)
    for i in range(35):
        Product.objects.create(organization=org, sku=f"SKU{i}", name=f"Own {i:02d}", cost_price=1, sale_price=2)
    client.force_login(user)
    response = client.get("/records/products/")
    assert len(response.context["rows"]) == 30
    assert "PRIVATE_PRODUCT" not in response.content.decode()
    response = client.get("/records/products/?page=2")
    assert len(response.context["rows"]) == 5
    response = client.get("/records/products/?q=SECRET")
    assert response.context["page"].paginator.count == 0
    response = client.get("/records/products/?q=Own+03")
    assert response.context["page"].paginator.count == 1


def test_inactive_organization_hidden(client, owner):
    user, org = owner
    org.is_active = False
    org.save()
    client.force_login(user)
    assert client.get("/").context["organization"] is None if "organization" in client.get("/").context else True
    assert "Test owner's organization" not in client.get("/records/products/").content.decode()


def test_ambiguous_organization_denied(client, owner):
    user, _ = owner
    Membership.objects.create(user=user, organization=Organization.objects.create(name="Second"), role="OWNER")
    client.force_login(user)
    assert client.get("/").status_code == 403


def test_merchandiser_cannot_import_or_recalculate(client, owner):
    user, _ = owner
    Membership.objects.filter(user=user).update(role=Membership.Role.MERCHANDISER)
    client.force_login(user)
    assert client.get("/imports/sales/").status_code == 403
    assert client.post("/forecasts/generate/").status_code == 403


def test_forecast_requires_post_and_csrf(owner):
    client = Client(enforce_csrf_checks=True)
    client.force_login(owner[0])
    assert client.get("/forecasts/generate/").status_code == 405
    assert client.post("/forecasts/generate/").status_code == 403
    assert client.post("/imports/sales/").status_code == 403
    assert client.post("/accounts/logout/").status_code == 403


def test_owner_login_logout_and_no_open_redirect(client, owner):
    assert client.post("/accounts/login/?next=https://evil.example/", {
        "username": "owner", "password": "fixture-password",
    }).url == "/"
    assert client.get("/accounts/logout/").status_code == 405
    assert client.post("/accounts/logout/").status_code == 302
    assert client.get("/").status_code == 302


def test_server_admin_forbidden_even_for_staff(client, owner):
    user, _ = owner
    user.is_staff = True
    user.save()
    client.force_login(user)
    with override_settings(IS_PRODUCTION=True):
        assert client.get("/admin/").status_code == 403


@pytest.mark.parametrize("command", ["seed_demo", "seed_business_demo"])
def test_server_blocks_legacy_demo_commands(db, command):
    with override_settings(IS_PRODUCTION=True, ALLOW_DEMO_SEED=False):
        with pytest.raises(CommandError):
            call_command(command)
    assert not User.objects.exists()
    assert not Organization.objects.exists()


def test_bootstrap_requires_confirmation(db):
    with override_settings(IS_PRODUCTION=True):
        with pytest.raises(CommandError):
            call_command("bootstrap_pilot", username="owner")
    assert not User.objects.exists()


def test_bootstrap_rejects_existing_database(owner):
    with override_settings(IS_PRODUCTION=True):
        with pytest.raises(CommandError, match="не пустая"):
            call_command("bootstrap_pilot", username="new", confirm_demo=True)
    assert User.objects.count() == 1


def test_bootstrap_strong_password_and_disabled_demo(db):
    output = StringIO()
    with override_settings(IS_PRODUCTION=True, ALLOW_DEMO_SEED=False):
        with patch("getpass.getpass", return_value="Long-test-Fixture!71"):
            call_command("bootstrap_pilot", username="pilot_owner", confirm_demo=True, stdout=output)
        call_command("check_pilot_ready")
    user = User.objects.get(username="pilot_owner")
    assert user.check_password("Long-test-Fixture!71")
    assert not user.is_staff and not user.is_superuser
    demo = User.objects.get(username="demo")
    assert not demo.is_active and not demo.has_usable_password() and not demo.is_superuser
    assert "Long-test-Fixture!71" not in output.getvalue()
    assert "demo12345" not in output.getvalue()


def test_bootstrap_weak_password_changes_nothing(db):
    with override_settings(IS_PRODUCTION=True), patch("getpass.getpass", return_value="123"):
        with pytest.raises(CommandError):
            call_command("bootstrap_pilot", username="pilot_owner", confirm_demo=True)
    assert not User.objects.exists()
    assert not Organization.objects.exists()


def test_password_change(client, owner):
    client.force_login(owner[0])
    response = client.post("/accounts/password/", {
        "old_password": "fixture-password", "new_password1": "Changed-fixture-761!Password",
        "new_password2": "Changed-fixture-761!Password",
    })
    assert response.status_code == 302
    owner[0].refresh_from_db()
    assert owner[0].check_password("Changed-fixture-761!Password")


def test_release_excludes_sensitive_paths(monkeypatch, tmp_path):
    spec = importlib.util.spec_from_file_location("builder", ROOT / "scripts/build_release.py")
    builder = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(builder)
    monkeypatch.setattr(builder, "ROOT", tmp_path)
    for relative in (".env", ".env.server", "db.sqlite3", "deploy/tls/privkey.pem",
                     "backups/data.dump", "core/__pycache__/models.pyc", "scripts/.env.server"):
        assert not builder.included(tmp_path / relative)
    for relative in ("compose.server.yml", ".env.server.example", "deploy/nginx.conf", "core/views.py"):
        assert builder.included(tmp_path / relative)


def test_server_has_no_public_bindings():
    text = (ROOT / "compose.server.yml").read_text()
    assert '"127.0.0.1:8443:443"' in text
    assert text.count("ports:") == 1
    assert "internal: true" in text
    assert "DJANGO_DEBUG: \"0\"" in text


def test_proxy_overwrites_trusted_scheme_and_limits_login():
    text = (ROOT / "deploy/nginx.conf").read_text()
    assert "proxy_set_header X-Forwarded-Proto https;" in text
    assert "limit_req zone=login" in text
    assert "limit_req_status 429" in text


def test_ready_rejects_active_demo(owner):
    User.objects.create_user("demo", password="fixture")
    with override_settings(IS_PRODUCTION=True), pytest.raises(CommandError):
        call_command("check_pilot_ready")


def test_health_failure_hides_database_error(client):
    with patch("core.views.connection.cursor", side_effect=DatabaseError("sensitive_connection_string")):
        response = client.get("/health/")
    assert response.status_code == 503
    assert "sensitive" not in response.content.decode()


def load_settings(monkeypatch, **changes):
    for key in ("DATABASE_URL", "POSTGRES_HOST", "POSTGRES_DB", "POSTGRES_USER", "POSTGRES_PASSWORD",
                "DJANGO_SECRET_KEY", "DJANGO_DEBUG", "DJANGO_ALLOWED_HOSTS", "DJANGO_CSRF_TRUSTED_ORIGINS"):
        monkeypatch.delenv(key, raising=False)
    defaults = {
        "MMC_ENV": "production", "DJANGO_SECRET_KEY": "abcdefXYZ123456789!" * 4,
        "DJANGO_ALLOWED_HOSTS": "pilot.example.test", "DJANGO_CSRF_TRUSTED_ORIGINS": "https://pilot.example.test",
        "DATABASE_URL": "postgresql://fixture:fixture@localhost/fixture",
    }
    defaults.update(changes)
    for key, value in defaults.items():
        monkeypatch.setenv(key, value)
    spec = importlib.util.spec_from_file_location("isolated_settings", ROOT / "config/settings.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.mark.parametrize("changes", [
    {"DJANGO_SECRET_KEY": ""}, {"DJANGO_SECRET_KEY": "x" * 64},
    {"DJANGO_DEBUG": "1"}, {"DJANGO_ALLOWED_HOSTS": "*"},
    {"DJANGO_CSRF_TRUSTED_ORIGINS": "http://pilot.example.test"},
    {"DATABASE_URL": "sqlite:///db.sqlite3"}, {"DATABASE_URL": "unsupported://oops"},
])
def test_production_rejects_unsafe_config(monkeypatch, changes):
    from django.core.exceptions import ImproperlyConfigured
    with pytest.raises(ImproperlyConfigured):
        load_settings(monkeypatch, **changes)


def test_production_security_flags(monkeypatch):
    settings = load_settings(monkeypatch)
    assert not settings.DEBUG
    assert settings.SESSION_COOKIE_SECURE and settings.CSRF_COOKIE_SECURE
    assert settings.SECURE_SSL_REDIRECT
    assert not settings.ALLOW_DEMO_SEED
    assert settings.SECURE_PROXY_SSL_HEADER == ("HTTP_X_FORWARDED_PROTO", "https")


def test_database_url_decodes_credentials(monkeypatch):
    settings = load_settings(monkeypatch, DATABASE_URL="postgresql://user:p%40ss@host/db?sslmode=require")
    assert settings.DATABASES["default"]["PASSWORD"] == "p@ss"
    assert settings.DATABASES["default"]["OPTIONS"]["sslmode"] == "require"


def test_init_server_will_not_overwrite_secrets(tmp_path):
    import shutil
    scripts = tmp_path / "scripts"
    scripts.mkdir()
    shutil.copy(ROOT / "scripts/init_server.py", scripts / "init_server.py")
    subprocess.run([sys.executable, str(scripts / "init_server.py")], check=True, capture_output=True)
    before = (tmp_path / ".env.server").read_bytes()
    result = subprocess.run([sys.executable, str(scripts / "init_server.py")], capture_output=True)
    assert result.returncode != 0
    assert (tmp_path / ".env.server").read_bytes() == before
    if os.name != "nt":
        assert (tmp_path / ".env.server").stat().st_mode & 0o777 == 0o600
