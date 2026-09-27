"""No credentials are hard-coded or committed."""

import re
import subprocess
from pathlib import Path

import pytest
from sqlalchemy.engine import make_url

from app.core.config import ConfigurationError, load_settings

PROJECT_ROOT = Path(__file__).resolve().parents[2]
EXCLUDED_DIRS = {".venv", "venv", ".git", "__pycache__", ".pytest_cache", ".idea", ".vscode",
                 "node_modules", "dist"}  # UI track: installed JS packages and build output (git-ignored)
EXCLUDED_FILES = {".env"}  # the only place real values may live; git-ignored
TEXT_SUFFIXES = {".py", ".ini", ".toml", ".cfg", ".txt", ".md", ".mako", ".example", ".sql", ".json", ".yml", ".yaml"}

# Placeholder passwords that are allowed to appear in examples and tests.
ALLOWED_PLACEHOLDER_PASSWORDS = {"change-me"}

CREDENTIAL_URL = re.compile(r"\b[a-z][a-z0-9+]*://[^\s:/@'\"]+:([^\s@'\"]+)@")
ASSIGNED_SECRET = re.compile(
    r"""(?i)\b(password|passwd|secret|api_key|token)\s*[:=]\s*['"]([^'"\s]{4,})['"]"""
)


def project_text_files() -> list[Path]:
    files = []
    for path in PROJECT_ROOT.rglob("*"):
        if any(part in EXCLUDED_DIRS for part in path.relative_to(PROJECT_ROOT).parts):
            continue
        if path.is_file() and path.name not in EXCLUDED_FILES:
            if path.suffix in TEXT_SUFFIXES or path.name.startswith(".env"):
                files.append(path)
    return files


def test_scan_covers_the_source_tree():
    scanned = {p.relative_to(PROJECT_ROOT).as_posix() for p in project_text_files()}
    for expected in ["app/core/config.py", "alembic/env.py", "alembic.ini", ".env.example"]:
        assert expected in scanned


def test_no_credentials_embedded_in_urls():
    offenders = []
    for path in project_text_files():
        for match in CREDENTIAL_URL.finditer(path.read_text(encoding="utf-8", errors="ignore")):
            if match.group(1) not in ALLOWED_PLACEHOLDER_PASSWORDS:
                offenders.append(f"{path.relative_to(PROJECT_ROOT)}: {match.group(0)}")
    assert offenders == []


def test_no_secret_literals_assigned_in_code():
    offenders = []
    for path in project_text_files():
        for match in ASSIGNED_SECRET.finditer(path.read_text(encoding="utf-8", errors="ignore")):
            if match.group(2) not in ALLOWED_PLACEHOLDER_PASSWORDS:
                offenders.append(f"{path.relative_to(PROJECT_ROOT)}: {match.group(0)}")
    assert offenders == []


def test_alembic_ini_has_no_database_url():
    ini = (PROJECT_ROOT / "alembic.ini").read_text(encoding="utf-8")
    assert not re.search(r"(?m)^\s*sqlalchemy\.url\s*=", ini)


def test_configured_passwords_do_not_appear_in_any_project_file():
    """The real passwords from the local .env must not leak into any other file."""
    try:
        settings = load_settings()
    except ConfigurationError:
        pytest.skip("no local configuration to compare against")
    secrets = {settings.database_url_parsed.password}
    if settings.test_database_url:
        secrets.add(make_url(settings.test_database_url.get_secret_value()).password)
    secrets = {s for s in secrets if s and s not in ALLOWED_PLACEHOLDER_PASSWORDS}
    if not secrets:
        pytest.skip("configured passwords are placeholders")
    leaks = [
        str(path.relative_to(PROJECT_ROOT))
        for path in project_text_files()
        if any(secret in path.read_text(encoding="utf-8", errors="ignore") for secret in secrets)
    ]
    assert leaks == []


def test_env_file_is_git_ignored():
    result = subprocess.run(
        ["git", "check-ignore", "--quiet", ".env"], cwd=PROJECT_ROOT, capture_output=True
    )
    assert result.returncode == 0, ".env must be listed in .gitignore"


def test_env_example_is_not_ignored_and_uses_placeholders():
    result = subprocess.run(
        ["git", "check-ignore", "--quiet", ".env.example"], cwd=PROJECT_ROOT, capture_output=True
    )
    assert result.returncode == 1, ".env.example must be committed"
    example = (PROJECT_ROOT / ".env.example").read_text(encoding="utf-8")
    passwords = CREDENTIAL_URL.findall(example)
    assert passwords and set(passwords) <= ALLOWED_PLACEHOLDER_PASSWORDS
