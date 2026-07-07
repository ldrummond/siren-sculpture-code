from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml


DEFAULT_CONFIG_PATH = "/opt/sculpture/provisioning/settings/provisioning.yaml"


class ProvisioningConfigError(RuntimeError):
    """Raised when provisioning configuration is missing or invalid."""


@dataclass(frozen=True)
class ProvisioningConfig:
    data: dict[str, Any]
    path: Path

    def get(self, dotted_key: str, default: Any = None) -> Any:
        value: Any = self.data
        for part in dotted_key.split("."):
            if not isinstance(value, dict) or part not in value:
                return default
            value = value[part]
        return value


def load_config(path: str | os.PathLike[str] | None = None) -> ProvisioningConfig:
    config_path = Path(path or os.environ.get("PROVISIONING_CONFIG", DEFAULT_CONFIG_PATH))
    if not config_path.exists():
        raise ProvisioningConfigError(f"Provisioning config file not found: {config_path}")
    try:
        raw = yaml.safe_load(config_path.read_text(encoding="utf-8"))
    except yaml.YAMLError as exc:
        raise ProvisioningConfigError(f"Invalid YAML in {config_path}: {exc}") from exc
    if not isinstance(raw, dict):
        raise ProvisioningConfigError(f"Provisioning config {config_path} must contain a YAML mapping")

    required = [
        "provisioning.enabled",
        "network.interface",
        "wifi.connection_name",
        "ble.provisioning.enabled",
        "ble.provisioning.device_name",
        "ble.provisioning.service_uuid",
        "ble.provisioning.command_characteristic_uuid",
        "ble.provisioning.status_characteristic_uuid",
    ]
    missing = [key for key in required if _deep_get(raw, key) is None]
    if missing:
        raise ProvisioningConfigError(f"Provisioning config missing required keys: {', '.join(missing)}")
    return ProvisioningConfig(data=raw, path=config_path)


def _deep_get(data: dict[str, Any], dotted_key: str) -> Any:
    value: Any = data
    for part in dotted_key.split("."):
        if not isinstance(value, dict) or part not in value:
            return None
        value = value[part]
    return value
