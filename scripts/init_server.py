"""Generate server settings locally. Never overwrites existing secrets."""
import argparse
import os
import re
import secrets
from pathlib import Path


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--host", default="localhost", help="Bare hostname, no protocol or port")
    parser.add_argument("--port", default=8443, type=int)
    args = parser.parse_args()
    if not re.fullmatch(r"[A-Za-z0-9](?:[A-Za-z0-9.-]*[A-Za-z0-9])?", args.host) or not 1 <= args.port <= 65535:
        parser.error("Invalid host or port")
    root = Path(__file__).resolve().parent.parent
    path = root / ".env.server"
    origin = f"https://{args.host}" + (f":{args.port}" if args.port != 443 else "")
    text = (
        "POSTGRES_DB=micromarket\nPOSTGRES_USER=micromarket\n"
        f"POSTGRES_PASSWORD={secrets.token_hex(32)}\n"
        f"DJANGO_SECRET_KEY={secrets.token_hex(48)}\n"
        f"DJANGO_ALLOWED_HOSTS={args.host}\n"
        f"DJANGO_CSRF_TRUSTED_ORIGINS={origin}\n"
    )
    try:
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    except FileExistsError:
        parser.exit(1, ".env.server already exists; not overwritten. Keep existing database credentials.\n")
    with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as stream:
        stream.write(text)
    (root / "deploy" / "tls").mkdir(mode=0o700, parents=True, exist_ok=True)
    (root / "backups").mkdir(mode=0o700, exist_ok=True)
    print("Created .env.server (secrets not displayed). Ports are unchanged; nothing deployed.")


if __name__ == "__main__":
    main()
