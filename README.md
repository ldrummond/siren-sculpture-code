# Sculpture Audio Controller

Raspberry Pi audio controller for a public, solar-powered sculpture installation. The app plays a long ambient audio file through a USB DAC, starts automatically after power loss, exposes BLE provisioning/control services, and includes scripts for repeatable Pi installation.

## Target Hardware

- Raspberry Pi 3 A+
- Raspberry Pi OS Lite 32-bit
- Witty Pi 4 Mini
- USB audio DAC
- AIYIMA amplifier with AUX input
- Solar and battery power system

## Project Layout

- `siren-app/`: siren-specific audio controller, audio assets, config, scripts, and `systemd` units.
- `provisioning/`: reusable BLE Wi-Fi provisioning module, config, scripts, and `systemd` units.
- `scripts/`: root orchestration only, such as install, deploy, Raspberry Pi Connect setup, and release helpers.
- `config/`: shared host-level config that is not owned by a component, currently log rotation.
- `web-bluetooth/`: standalone Web Bluetooth pages to host on your own web server, not on the Pi.

## Fresh Pi Install

On a fresh Raspberry Pi OS Lite install:

```bash
sudo apt update
sudo apt install -y git
sudo git clone https://github.com/YOURUSER/sculpture-audio-controller.git /opt/sculpture
cd /opt/sculpture
sudo ./scripts/install.sh
```

The default runtime user is `admin`. Override it if needed:

```bash
sudo SCULPTURE_USER=myuser ./scripts/install.sh
```

The installer enables Raspberry Pi Connect Lite, direct BLE provisioning/control, and the BLE network provisioning service by default. Disable them only when intentionally building a locked-down image:

```bash
sudo ENABLE_RPI_CONNECT=0 ENABLE_PROVISIONING=0 ./scripts/install.sh
```

Direct BLE services can be toggled independently:

```bash
sudo ENABLE_BLE_PROVISIONING=0 ENABLE_BLE_CONTROL=0 ./scripts/install.sh
```

If you want Connect to sign in unattended, generate a Raspberry Pi Connect auth key and pass it at install time. The key is staged on the Pi, not committed to this repo:

```bash
sudo RPI_CONNECT_AUTH_KEY="rpuak_..." ./scripts/install.sh
```

The installer does not reboot automatically. Reboot after install before field testing:

```bash
sudo reboot
```

## Audio Files

The default config expects:

```text
/opt/sculpture/siren-app/assets/audio/ambient.wav
```

Large audio files are ignored by Git. Copy them with `scp`, rsync, a USB drive, Git LFS, or a GitHub Release asset.

Test playback:

```bash
/opt/sculpture/siren-app/scripts/test-audio.sh
```

## Network Provisioning

The reusable provisioning module is separate from the siren audio code. It receives BLE commands and uses NetworkManager through `nmcli` to scan for and join Wi-Fi networks.

Default low-power behavior:

1. Direct BLE provisioning runs as `sculpture-ble-provisioning.service`.
2. The Raspberry Pi does not create or host a setup access point.
3. The standalone Web Bluetooth page can send Wi-Fi credentials directly over BLE.
4. The Pi uses NetworkManager to scan for networks and try a Wi-Fi connection.

The BLE provisioning web page is:

```text
web-bluetooth/provisioning.html
```

Host it from your own HTTPS site or another browser context that supports Web Bluetooth. The Pi does not serve this page; it only exposes a BLE GATT service. The page connects to the Pi's `SculptureProvisioning` service and sends commands such as:

```text
status
scan_wifi
update_wifi_credentials
try_connect_wifi
connect_wifi
```

Configuration lives in:

```text
/opt/sculpture/provisioning/settings/provisioning.yaml
```

Useful commands:

```bash
sudo systemctl status sculpture-ble-provisioning.service
journalctl -u sculpture-ble-provisioning.service -n 100 --no-pager
```

## BLE Control

The siren app also exposes a direct BLE control service:

```text
sculpture-ble-control.service
```

The standalone control page is:

```text
web-bluetooth/siren-control.html
```

It sends simple commands over BLE:

```text
play
pause
stop
restart
resume_normal
status
```

Web Bluetooth requires a supported browser and a secure context. In practice, host these HTML files from your own HTTPS site for field use. The Raspberry Pi only receives BLE commands and returns compact JSON status.

Pi BLE note: the repo defines provisioning and siren control as separate systemd services because they are separate concerns. On the target Pi, verify that BlueZ can advertise both services concurrently with `bless`. If the adapter only advertises one service reliably, merge them into one BLE gateway service that exposes both GATT services from a single process.

Disable provisioning if needed:

```bash
sudo ENABLE_PROVISIONING=0 /opt/sculpture/scripts/deploy.sh
```

## Raspberry Pi Connect

The installer installs `rpi-connect-lite`, enables Connect for the runtime user, and enables user lingering so remote shell can stay available without an active local login session.

If no auth key was provided during install, link the Pi manually:

```bash
rpi-connect signin
```

Check Connect networking:

```bash
rpi-connect doctor
```

## Services and Logs

```bash
sudo systemctl status sculpture-audio.service
sudo systemctl status sculpture-healthcheck.timer
sudo systemctl status sculpture-ble-provisioning.service
sudo systemctl status sculpture-ble-control.service
journalctl -u sculpture-audio.service -n 100 --no-pager
```

Application logs are written to:

```text
/var/log/sculpture/sculpture.log
```

## Deploy Updates

On an existing Pi checkout:

```bash
cd /opt/sculpture
sudo ./scripts/deploy.sh
```

This pulls the latest Git checkout when possible, updates Python dependencies, refreshes service files, and restarts the services. It does not delete audio files.

For direct workstation deploys from your Mac, run:

```bash
./scripts/sync-to-pi.sh
```

The sync script defaults to `admin@10.10.30.112:/opt/sculpture`, copies the repo with `rsync`, and then runs `sudo /opt/sculpture/scripts/deploy.sh` on the Pi. It prompts for SSH/sudo passwords as needed; the password is not stored in the repo.

Useful overrides:

```bash
PI_HOST=raspberrypi.local ./scripts/sync-to-pi.sh
RUN_INSTALL=1 ./scripts/sync-to-pi.sh
RUN_DEPLOY=0 ./scripts/sync-to-pi.sh
SYNC_AUDIO=1 ./scripts/sync-to-pi.sh
```

## Witty Pi Scheduling

Witty Pi should own the hard power cycle:

1. Wake the Pi in the morning.
2. Pi boots and `systemd` starts the audio and BLE services.
3. Audio starts automatically.
4. Witty Pi initiates clean evening shutdown.
5. Witty Pi cuts power.
6. RTC keeps time through power interruptions.

The Python audio service also checks the configured active window, but that is a playback guard, not the primary power scheduler.

The tracked starter schedule is:

```text
siren-app/config/wittypi/schedule.wpi
```

Confirm the exact schedule syntax on the target Witty Pi software before public installation.

## Configuration

The app loads:

```text
/opt/sculpture/siren-app/config/sculpture.yaml
```

Override this path for testing or custom deployment:

```bash
SCULPTURE_CONFIG=/path/to/sculpture.yaml
PROVISIONING_CONFIG=/path/to/provisioning.yaml
```

## Development Checks

The code targets Python 3.9+.

```bash
python -m pytest
python -m compileall siren-app provisioning tests
bash -n scripts/*.sh
```

## Field Maintenance Checklist

Before installation:

- Confirm audio plays through amp.
- Confirm BLE provisioning works from the hosted Web Bluetooth page.
- Confirm BLE siren control works from the hosted Web Bluetooth page.
- Confirm Raspberry Pi Connect remote shell works after the Pi joins Wi-Fi.
- Confirm system time and Witty Pi RTC are correct.
- Confirm Witty Pi morning/evening schedule.
- Confirm low-voltage behavior if used.
- Confirm Pi recovers after power interruption.
- Confirm logs are being written.
- Clone the working SD card.
- Keep at least one spare SD card with the maintenance kit.
