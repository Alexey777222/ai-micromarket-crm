"""Portable release builder: allowlist, no secrets or live databases."""
import argparse
import hashlib
import os
import re
import tempfile
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
TOP_FILES = {
    ".env.example", ".env.server.example", ".gitignore", ".dockerignore",
    "CHANGELOG.md", "Dockerfile", "docker-compose.yml", "compose.server.yml",
    "entrypoint.sh", "install_demo.bat", "start_demo.bat", "manage.py",
    "pyproject.toml", "pytest.ini", "README.md", "START_HERE.md", "VERSION",
    "requirements-web.txt", "requirements-server.txt", "requirements-bot.txt", "requirements.txt",
}
DIRS = {"config", "core", "docs", "samples", "scripts", "static", "templates", "tests", "deploy"}
EXCLUDED = {"__pycache__", ".pytest_cache", ".ruff_cache", ".venv", "venv", ".git", "tls", "backups", "media"}
EXTENSIONS = {".py", ".md", ".txt", ".html", ".css", ".js", ".csv", ".sh", ".bat", ".ps1", ".conf", ".yml", ".yaml"}


def included(path):
    relative = path.relative_to(ROOT)
    if len(relative.parts) == 1:
        return relative.name in TOP_FILES
    return (
        relative.parts[0] in DIRS
        and not any(part.startswith(".") or part in EXCLUDED for part in relative.parts)
        and path.suffix in EXTENSIONS
        and not path.is_symlink()
    )


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--output-dir", type=Path, default=ROOT.parent)
    args = parser.parse_args()
    version = (ROOT / "VERSION").read_text(encoding="utf-8").strip()
    if not re.fullmatch(r"\d+\.\d+\.\d+", version):
        parser.error("Invalid VERSION")
    paths = sorted(p for p in ROOT.rglob("*") if p.is_file() and not p.is_symlink() and included(p))
    missing = TOP_FILES - {p.name for p in paths if p.parent == ROOT}
    if missing:
        parser.error(f"Missing required files: {sorted(missing)}")
    args.output_dir.mkdir(parents=True, exist_ok=True)
    target = args.output_dir.resolve() / f"micromarket-v{version}.zip"
    if target.exists():
        parser.error("Archive exists. Choose a new output directory; existing releases are preserved.")
    fd, name = tempfile.mkstemp(suffix=".zip", dir=args.output_dir)
    os.close(fd)
    temporary = Path(name)
    try:
        with zipfile.ZipFile(temporary, "w", zipfile.ZIP_DEFLATED) as archive:
            for path in paths:
                archive.write(path, "micromarket-control/" + path.relative_to(ROOT).as_posix())
        with zipfile.ZipFile(temporary) as archive:
            if archive.testzip():
                raise RuntimeError("Archive integrity check failed")
        temporary.rename(target)
    finally:
        if temporary.exists():
            temporary.unlink()
    print(f"Created: {target}")
    print(f"Files: {len(paths)}, bytes: {target.stat().st_size}")
    with target.open("rb") as stream:
        print(f"SHA256: {hashlib.file_digest(stream, 'sha256').hexdigest()}")


if __name__ == "__main__":
    main()
