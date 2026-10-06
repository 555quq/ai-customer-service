import json

import pytest

from src.utils.config_manager import ConfigEncryptionError, ConfigManager


KEY_A = "11" * 32
KEY_B = "22" * 32


def test_runtime_secrets_are_encrypted_and_reloadable(tmp_path):
    config_file = tmp_path / "runtime.json"
    manager = ConfigManager(str(config_file), encryption_key=KEY_A)
    manager.update({
        "model": {"api_key": "model-secret", "model": "deepseek-chat"},
        "chatwoot": {"api_token": "chatwoot-secret"},
    })

    persisted = config_file.read_text(encoding="utf-8")
    assert "model-secret" not in persisted
    assert "chatwoot-secret" not in persisted
    assert persisted.count("fernet:v1:") == 2

    reloaded = ConfigManager(str(config_file), encryption_key=KEY_A)
    assert reloaded.get("model.api_key") == "model-secret"
    assert reloaded.get("chatwoot.api_token") == "chatwoot-secret"


def test_plaintext_secrets_are_migrated_on_first_load(tmp_path):
    config_file = tmp_path / "runtime.json"
    config_file.write_text(
        json.dumps({"model": {"api_key": "legacy-plaintext", "model": "legacy"}}),
        encoding="utf-8",
    )

    manager = ConfigManager(str(config_file), encryption_key=KEY_A)

    assert manager.get("model.api_key") == "legacy-plaintext"
    assert "legacy-plaintext" not in config_file.read_text(encoding="utf-8")


def test_wrong_encryption_key_fails_closed(tmp_path):
    config_file = tmp_path / "runtime.json"
    manager = ConfigManager(str(config_file), encryption_key=KEY_A)
    manager.update({"model": {"api_key": "protected"}})

    with pytest.raises(ConfigEncryptionError, match="could not be decrypted"):
        ConfigManager(str(config_file), encryption_key=KEY_B)


def test_dotted_updates_expand_and_masked_values_preserve_secrets(tmp_path):
    manager = ConfigManager(str(tmp_path / "runtime.json"), encryption_key=KEY_A)
    manager.update({"model": {"api_key": "model-secret"}})
    masked = manager.get_public()["model"]["api_key"]

    normalized = manager.update({
        "model.api_key": masked,
        "ai.confidence_threshold": 0.82,
    })

    assert normalized == {
        "model": {"api_key": masked},
        "ai": {"confidence_threshold": 0.82},
    }
    assert manager.get("model.api_key") == "model-secret"
    assert manager.get("ai.confidence_threshold") == 0.82
    assert manager.get("ai.confidence_threshold", None) is not None
    assert "ai.confidence_threshold" not in manager.config
