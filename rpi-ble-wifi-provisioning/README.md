# BLE Wi-Fi Provisioning Handler

Wi-Fi provisioning domain package for the Siren sculpture's shared Bluetooth
Low Energy gateway. A separately hosted Web Bluetooth page scans nearby
networks, sends credentials, and asks NetworkManager on the Pi to connect.

This directory is part of the `siren-project` monorepo. It is not a standalone
Pi daemon and must not create a second BLE advertisement. The only BLE server
is `sculpture-ble-control.service`, implemented by
`siren_app.ble_gateway` in `siren-sculpture-code`.

## Layout

- `provisioning/provisioning_core/`: provisioning command handler, config loader, and `nmcli` operations.
- `provisioning/settings/provisioning.yaml`: provisioning and network defaults.
- `web-bluetooth/provisioning.html`: static page to host on an HTTPS web server.
- `tests/`: handler, network, and configuration tests.

The root `sync-to-pi.sh` copies this directory to
`/opt/sculpture/vendor/rpi-ble-wifi-provisioning`. The sculpture initializer
installs it into `/opt/sculpture/.venv`; do not install it separately.

## BLE Contract

```text
Shared service: 9f0d0101-7b6d-4d2c-9f4f-6f70726f7601
Provisioning command: 9f0d0002-7b6d-4d2c-9f4f-6f70726f7601
Provisioning status: 9f0d0003-7b6d-4d2c-9f4f-6f70726f7601
```

Supported actions are `status`, `scan_wifi`, `scan_wifi_page`,
`update_wifi_credentials`, `try_connect_wifi`, `connect_wifi`, and
`connect_saved_wifi`.

Wi-Fi scans are paged to stay below the practical GATT response limit. A
network includes `saved: true` when NetworkManager already has a profile for
its SSID. Selecting a saved network activates that profile without sending its
stored password over BLE.

Connection attempts run in a background thread so `nmcli` work does not block
the GATT write callback. The hosted page polls the status characteristic until
the result is `connected` or `failed`.

## Configuration

The deployed config is:

```text
/opt/sculpture/vendor/rpi-ble-wifi-provisioning/provisioning/settings/provisioning.yaml
```

`network.connectivity_required` controls whether a candidate Wi-Fi connection
must reach NetworkManager's `full` connectivity state. Set it to `false` for a
local network without internet access.

The service UUID must match `siren-app/config/sculpture.yaml`; command and
status characteristic UUIDs must remain unique across both domains.

## Development

Run this package's tests from its directory:

```bash
python -m pytest -q
```

Host `web-bluetooth/provisioning.html` over HTTPS and use Chrome or Edge.
The page is never served by the Raspberry Pi.
