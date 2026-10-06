from pathlib import Path

import pytest

from src.auth import passwords
from src.auth.tokens import AuthConfigurationError
from src.config import Settings
from src.services.ai_config import AIConfig


def test_fresh_settings_do_not_include_usable_credentials(monkeypatch):
    for name in (
        "ADMIN_PASSWORD",
        "ADMIN_PASSWORD_HASH",
        "AGENT_PASSWORD",
        "AGENT_PASSWORD_HASH",
        "DIFY_API_KEY",
        "AI_OPENAI_API_KEY",
    ):
        monkeypatch.delenv(name, raising=False)

    settings = Settings(_env_file=None)
    ai = AIConfig(_env_file=None)

    assert settings.admin_password is None
    assert settings.agent_password is None
    assert settings.dify_api_key is None
    assert ai.openai_api_key is None


def test_unconfigured_development_login_is_rejected_explicitly(monkeypatch):
    monkeypatch.setattr(passwords.settings, "environment", "development")
    monkeypatch.setattr(passwords.settings, "admin_username", "admin")
    monkeypatch.setattr(passwords.settings, "admin_password", None)
    monkeypatch.setattr(passwords.settings, "admin_password_hash", None)
    monkeypatch.setattr(passwords.config_manager, "get", lambda *_args: {})

    with pytest.raises(AuthConfigurationError, match="not configured"):
        passwords.authenticate_configured_user("admin", "anything", "admin")


def test_repository_defaults_do_not_contain_historical_weak_secrets():
    root = Path(__file__).resolve().parents[2]
    paths = (
        root / "docker-compose.yml",
        root / "bridge-service/src/config.py",
        root / "bridge-service/src/services/ai_config.py",
    )
    sources = [path.read_text(encoding="utf-8") for path in paths]

    for forbidden in ("changeme", "admin123", "agent123", "replace_with_random_string"):
        assert all(forbidden not in source for source in sources)
