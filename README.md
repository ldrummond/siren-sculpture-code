# Siren Project

Shared Raspberry Pi sculpture project containing the audio controller, BLE
Wi-Fi provisioning package, desktop deployment tools, and hardware reference
files.

## Layout

- `siren-sculpture-code/`: code installed at `/opt/sculpture` on the Pi.
- `rpi-ble-wifi-provisioning/`: provisioning handler installed into the
  sculpture virtual environment and mounted into the shared BLE gateway.
- `reference/`: laptop-side Witty Pi manuals and vendor sample files.
- `sync-to-pi.sh`: copies both application folders to the Pi and optionally
  runs installation.
- `pi-status.sh`: prints relevant service statuses from the Pi.
- `sync.env.example`: template for local SSH and deployment defaults.

Create the local deployment configuration once:

```bash
cp sync.env.example sync.env
```

`sync.env` is ignored by Git so machine-specific connection details remain local.

## Desktop Commands

```bash
./sync-to-pi.sh
./pi-status.sh
```

`sync-to-pi.sh` prompts for the Pi hostname or IP address, whether to initialize
a fresh Pi, and whether to install and restart services after syncing. Both
action prompts default to `no`, so answering `no` to both copies files only.
