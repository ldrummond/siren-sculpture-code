from __future__ import annotations

from pathlib import Path

import pytest

from provisioning_core.config import ProvisioningConfigError, load_config


def test_load_provisioning_config_valid_yaml(tmp_path: Path) -> None:
    path = tmp_path / "provisioning.yaml"
    path.write_text(
        """
provisioning:
  enabled: true
  state_dir: "/tmp/sculpture-provisioning"
network:
  interface: "wlan0"
wifi:
  connection_name: "sculpture-site-wifi"
ble:
  provisioning:
    enabled: true
    device_name: "SculptureProvisioning"
    service_uuid: "9f0d0001-7b6d-4d2c-9f4f-6f70726f7601"
    command_characteristic_uuid: "9f0d0002-7b6d-4d2c-9f4f-6f70726f7601"
    status_characteristic_uuid: "9f0d0003-7b6d-4d2c-9f4f-6f70726f7601"
""".strip(),
        encoding="utf-8",
    )

    config = load_config(path)

    assert config.get("network.interface") == "wlan0"
    assert config.get("ble.provisioning.device_name") == "SculptureProvisioning"


def test_load_provisioning_config_missing_required_value(tmp_path: Path) -> None:
    path = tmp_path / "bad.yaml"
    path.write_text("provisioning:\n  enabled: true\n", encoding="utf-8")

    with pytest.raises(ProvisioningConfigError, match="missing required keys"):
        load_config(path)
