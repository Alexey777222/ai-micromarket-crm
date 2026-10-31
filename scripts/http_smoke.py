"""Gunicorn smoke using a NEW disposable SQLite demo DB, never the project DB."""
import http.cookiejar
import os
import re
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path


def main():
    if os.getenv("MMC_ENV", "local") != "local" or os.getenv("DATABASE_URL") or os.getenv("POSTGRES_HOST"):
        raise SystemExit("Use only local default SQLite demo, without external DB configuration.")
    with tempfile.TemporaryDirectory(prefix="mmc-http-smoke-") as temporary:
        env = {**os.environ, "DJANGO_DEBUG": "0",
               "DATABASE_URL": "sqlite:///" + str(Path(temporary) / "demo.sqlite3")}
        run_smoke(env)


def run_smoke(env):
    root = Path(__file__).resolve().parent.parent
    base = "http://127.0.0.1:8019"
    for command in (["migrate", "--noinput"], ["seed_business_demo"], ["collectstatic", "--noinput"]):
        subprocess.run([sys.executable, "manage.py", *command], cwd=root, env=env,
                       check=True, stdout=subprocess.DEVNULL)
    server = subprocess.Popen(
        [sys.executable, "-m", "gunicorn", "config.wsgi:application",
         "--bind", "127.0.0.1:8019", "--workers", "1"],
        cwd=root, env=env, stdout=subprocess.DEVNULL,
    )
    opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(http.cookiejar.CookieJar()))

    def read(route):
        with opener.open(base + route, timeout=10) as response:
            assert response.status == 200
            return response.read().decode()

    def post(route, data, page):
        csrf = re.search(r'name="csrfmiddlewaretoken" value="([^"]+)"', page).group(1)
        request = urllib.request.Request(
            base + route,
            data=urllib.parse.urlencode({**data, "csrfmiddlewaretoken": csrf}).encode(),
            headers={"Referer": base + route},
        )
        with opener.open(request, timeout=30) as response:
            assert response.status == 200
            return response.read().decode()

    try:
        for _ in range(50):
            if server.poll() is not None:
                raise RuntimeError("Gunicorn exited before readiness.")
            try:
                page = read("/accounts/login/")
                break
            except urllib.error.URLError:
                time.sleep(0.1)
        else:
            raise RuntimeError("Gunicorn readiness timeout.")
        page = post("/accounts/login/", {"username": "demo", "password": "demo12345"}, page)
        assert "account-bar" in page, "Demo login failed"
        for section in ["fridges", "products", "stock", "batches", "sales", "writeoffs", "forecasts"]:
            page = read("/records/" + section + "/")
            assert "account-bar" in page
        assert "header" in read("/static/css/portal.css")
        page = read("/")
        for _ in range(2):
            page = post("/forecasts/generate/", {}, page)
            assert "Создано рекомендаций" in page
        page = post("/accounts/logout/", {}, page)
        assert "Вход в MicroMarket Control" in page
        assert "Вход в MicroMarket Control" in read("/records/sales/")
        print("HTTP smoke passed: Gunicorn, login, 7 screens, static, two recalculations, logout.")
    finally:
        server.terminate()
        server.wait(timeout=10)


if __name__ == "__main__":
    main()
