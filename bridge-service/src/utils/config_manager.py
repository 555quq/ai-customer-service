"""Runtime configuration persistence, masking, and authenticated encryption."""

from __future__ import annotations

import base64
import binascii
import copy
import json
import os
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Optional

from cryptography.fernet import Fernet, InvalidToken
from loguru import logger

from ..config import settings


SECRET_MARKERS = ("api_key", "apikey", "token", "password", "secret")
ENCRYPTED_VALUE_KEY = "$encrypted"
ENCRYPTED_VALUE_PREFIX = "fernet:v1:"


class ConfigEncryptionError(RuntimeError):
    """Raised when protected runtime configuration cannot be encrypted or decrypted."""


def _is_secret_key(key: str) -> bool:
    normalized = key.lower().replace("-", "_")
    return any(marker in normalized for marker in SECRET_MARKERS)


def _mask_secret(value: Any) -> str:
    text = str(value or "")
    if not text:
        return ""
    if len(text) <= 8:
        return "********"
    return f"{text[:3]}***{text[-3:]}"


def sanitize_config(value: Any, key: str = "") -> Any:
    """Return a deep, client-safe copy without exposing configured secrets."""
    if _is_secret_key(key):
        return _mask_secret(value)
    if isinstance(value, dict):
        return {item_key: sanitize_config(item, item_key) for item_key, item in value.items()}
    if isinstance(value, list):
        return [sanitize_config(item) for item in value]
    return value


class RuntimeConfigCipher:
    """Fernet wrapper accepting the deployment's 32-byte hexadecimal key."""

    def __init__(self, key: str) -> None:
        raw_key = str(key or "").strip()
        try:
            if len(raw_key) == 64:
                fernet_key = base64.urlsafe_b64encode(bytes.fromhex(raw_key))
            else:
                decoded = base64.urlsafe_b64decode(raw_key.encode("ascii"))
                if len(decoded) != 32:
                    raise ValueError("decoded key must contain 32 bytes")
                fernet_key = raw_key.encode("ascii")
            self._fernet = Fernet(fernet_key)
        except (ValueError, TypeError, UnicodeError, binascii.Error) as exc:
            raise ConfigEncryptionError(
                "CONFIG_ENCRYPTION_KEY must be 64 hexadecimal characters or a Fernet key"
            ) from exc

    def encrypt(self, value: Any) -> dict[str, str]:
        payload = json.dumps(value, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
        token = self._fernet.encrypt(payload).decode("ascii")
        return {ENCRYPTED_VALUE_KEY: f"{ENCRYPTED_VALUE_PREFIX}{token}"}

    def decrypt(self, envelope: dict[str, Any]) -> Any:
        encoded = str(envelope.get(ENCRYPTED_VALUE_KEY, ""))
        if not encoded.startswith(ENCRYPTED_VALUE_PREFIX):
            raise ConfigEncryptionError("Unsupported encrypted runtime-config value")
        try:
            payload = self._fernet.decrypt(
                encoded.removeprefix(ENCRYPTED_VALUE_PREFIX).encode("ascii")
            )
            return json.loads(payload.decode("utf-8"))
        except (InvalidToken, ValueError, UnicodeError, json.JSONDecodeError) as exc:
            raise ConfigEncryptionError(
                "Runtime configuration could not be decrypted; verify CONFIG_ENCRYPTION_KEY"
            ) from exc


class ConfigManager:
    """Atomic runtime configuration manager with encrypted storage."""

    def __init__(self, config_file: Optional[str] = None, encryption_key: Optional[str] = None):
        environment_config_file = os.environ.get("AI_CS_RUNTIME_CONFIG_FILE", "").strip()
        self.config_file = (
            Path(config_file)
            if config_file
            else Path(environment_config_file)
            if environment_config_file
            else Path(__file__).resolve().parents[2] / "data" / "runtime" / "config.json"
        )
        configured_key = settings.config_encryption_key if encryption_key is None else encryption_key
        self._cipher = RuntimeConfigCipher(configured_key) if configured_key else None
        self.config: Dict[str, Any] = {}
        self.last_modified: Optional[datetime] = None
        self._load_config()

    @property
    def encryption_configured(self) -> bool:
        return self._cipher is not None

    @staticmethod
    def _is_encrypted_envelope(value: Any) -> bool:
        return isinstance(value, dict) and set(value) == {ENCRYPTED_VALUE_KEY}

    def _decrypt_from_storage(self, value: Any, key: str = "") -> tuple[Any, bool]:
        if self._is_encrypted_envelope(value):
            if self._cipher is None:
                raise ConfigEncryptionError(
                    "CONFIG_ENCRYPTION_KEY is required to read protected runtime configuration"
                )
            return self._cipher.decrypt(value), False
        if _is_secret_key(key) and value not in (None, ""):
            if self._cipher is None:
                raise ConfigEncryptionError(
                    "CONFIG_ENCRYPTION_KEY is required to migrate plaintext runtime secrets"
                )
            return value, True
        if isinstance(value, dict):
            result: dict[str, Any] = {}
            migration_required = False
            for item_key, item_value in value.items():
                decrypted, item_migration = self._decrypt_from_storage(item_value, item_key)
                result[item_key] = decrypted
                migration_required = migration_required or item_migration
            return result, migration_required
        if isinstance(value, list):
            result_list = []
            migration_required = False
            for item in value:
                decrypted, item_migration = self._decrypt_from_storage(item)
                result_list.append(decrypted)
                migration_required = migration_required or item_migration
            return result_list, migration_required
        return value, False

    def _encrypt_for_storage(self, value: Any, key: str = "") -> Any:
        if _is_secret_key(key) and value not in (None, ""):
            if self._cipher is None:
                raise ConfigEncryptionError(
                    "CONFIG_ENCRYPTION_KEY is required before saving runtime secrets"
                )
            return self._cipher.encrypt(value)
        if isinstance(value, dict):
            return {
                item_key: self._encrypt_for_storage(item_value, item_key)
                for item_key, item_value in value.items()
            }
        if isinstance(value, list):
            return [self._encrypt_for_storage(item) for item in value]
        return value

    def _load_config(self) -> None:
        if not self.config_file.exists():
            logger.warning(f"配置文件不存在: {self.config_file}")
            self.config = self._get_default_config()
            self._save_config()
            return
        try:
            with open(self.config_file, "r", encoding="utf-8") as stream:
                persisted = json.load(stream)
            self.config, migration_required = self._decrypt_from_storage(persisted)
            self.last_modified = datetime.fromtimestamp(self.config_file.stat().st_mtime)
            logger.info(f"配置已加载: {len(self.config)} 项")
            if migration_required:
                self._save_config()
                logger.info("运行时敏感配置已迁移为加密存储")
        except ConfigEncryptionError:
            logger.error("运行时配置解密失败")
            raise
        except Exception as exc:
            logger.error(f"加载配置失败: {exc}")
            raise

    def _save_config(self) -> None:
        try:
            self.config_file.parent.mkdir(parents=True, exist_ok=True)
            temp_file = self.config_file.with_suffix(self.config_file.suffix + ".tmp")
            persisted = self._encrypt_for_storage(self.config)
            with open(temp_file, "w", encoding="utf-8") as stream:
                json.dump(persisted, stream, indent=2, ensure_ascii=False)
                stream.flush()
                os.fsync(stream.fileno())
            temp_file.replace(self.config_file)
            if os.name != "nt":
                self.config_file.chmod(0o600)
            self.last_modified = datetime.now()
            logger.info("配置已保存")
        except Exception as exc:
            logger.error(f"保存配置失败: {exc}")
            raise

    @staticmethod
    def _get_default_config() -> Dict[str, Any]:
        return {
            "ai": {"confidence_threshold": 0.7, "max_retries": 3, "timeout": 30},
            "handoff": {
                "keywords": ["人工", "转人工", "人工客服", "投诉", "退款"],
                "unresolved_threshold": 3,
                "auto_assign": True,
            },
            "cache": {"ttl": 3600, "enabled": True},
            "rate_limit": {"requests_per_minute": 60, "burst": 100},
        }

    def get(self, key: str, default: Any = None) -> Any:
        value: Any = self.config
        for item in key.split("."):
            if isinstance(value, dict) and item in value:
                value = value[item]
            else:
                return default
        return value

    @staticmethod
    def normalize_update(config: Dict[str, Any]) -> Dict[str, Any]:
        """Expand dotted API keys while continuing to accept nested objects."""
        normalized: Dict[str, Any] = {}
        for key, value in config.items():
            keys = key.split(".")
            target = normalized
            for item in keys[:-1]:
                existing = target.get(item)
                if not isinstance(existing, dict):
                    existing = {}
                    target[item] = existing
                target = existing
            if isinstance(value, dict):
                nested = ConfigManager.normalize_update(value)
                current = target.get(keys[-1])
                if isinstance(current, dict):
                    ConfigManager._deep_merge(current, nested)
                else:
                    target[keys[-1]] = nested
            else:
                target[keys[-1]] = value
        return normalized

    @staticmethod
    def _deep_merge(target: Dict[str, Any], source: Dict[str, Any]) -> None:
        for key, value in source.items():
            if _is_secret_key(key) and value == _mask_secret(target.get(key)):
                continue
            if isinstance(value, dict) and isinstance(target.get(key), dict):
                ConfigManager._deep_merge(target[key], value)
            else:
                target[key] = copy.deepcopy(value)

    def set(self, key: str, value: Any) -> None:
        previous = copy.deepcopy(self.config)
        normalized = self.normalize_update({key: value})
        try:
            self._deep_merge(self.config, normalized)
            self._save_config()
            logger.info(f"配置已更新: {key} = {sanitize_config(value, key)}")
        except Exception:
            self.config = previous
            raise

    def get_all(self) -> Dict[str, Any]:
        return copy.deepcopy(self.config)

    def get_public(self) -> Dict[str, Any]:
        return sanitize_config(self.config)

    def update(self, config: Dict[str, Any]) -> Dict[str, Any]:
        normalized = self.normalize_update(config)
        previous = copy.deepcopy(self.config)
        try:
            self._deep_merge(self.config, normalized)
            self._save_config()
            logger.info(f"配置已批量更新: {len(config)} 项")
            return normalized
        except Exception:
            self.config = previous
            raise

    def restore(self, config: Dict[str, Any]) -> None:
        self.config = copy.deepcopy(config)
        self._save_config()

    def reload(self) -> None:
        logger.info("重新加载配置...")
        self._load_config()

    def reset(self) -> None:
        logger.warning("重置配置为默认值")
        previous = copy.deepcopy(self.config)
        try:
            self.config = self._get_default_config()
            self._save_config()
        except Exception:
            self.config = previous
            raise


config_manager = ConfigManager()
