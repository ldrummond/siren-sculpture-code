# Sculpture Audio Controller

Raspberry Pi audio controller for a public, solar-powered sculpture installation. The app plays a long audio file through a USB DAC, starts automatically after power loss, exposes a BLE control service, and includes scripts for repeatable Pi installation.

## Target Hardware

- Raspberry Pi 3 A+
- Raspberry Pi OS Lite 32-bit
- Witty Pi 4 Mini
- USB audio DAC
- AIYIMA amplifier with AUX input
- Solar and battery power system

## Project Layout

- `siren-app/`: siren-specific audio controller, audio assets, config, scripts, and `systemd` units.
- `../rpi-ble-wifi-provisioning/`: network-provisioning package mounted into the shared BLE gateway.
- `../sync-to-pi.sh`, `../pi-status.sh`, and `../sync.env`: laptop-side deployment and status tools.
- `scripts/`: Pi initialization, recurring install/update, Bluetooth checks, power cleanup, and journal export tools.
- `../reference/`: laptop-only Witty Pi manuals and vendor samples; it is not copied to the Pi.

## Fresh Pi Install

From the shared project root on your Mac, initialize a fresh Raspberry Pi OS
Lite installation with:

```bash
./sync-to-pi.sh
```

Enter the Pi hostname or IP address, then answer `yes` to the fresh-install
prompt. The initializer installs and starts the services, so a separate deploy
step is not needed during the same sync.

The initializer does not install or update Raspberry Pi firmware. Before making
any system changes, it requires pinned firmware revision
`7a0137617dd4a8496e566d23c01219923c409a79` and the tested `6.18.38-v7+`
32-bit kernel. If either does not match, initialization stops and prints the
manual `apt install rpi-update` and pinned `rpi-update` commands. Reboot after
installing firmware, confirm `uname -r`, and run the initializer again.

The default runtime user is `admin`. Override it if needed:

```bash
sudo SCULPTURE_USER=myuser ./scripts/initialize-pi.sh
```

The initializer enables the BLE control service and installs standard Witty Pi software with UWI disabled. It also runs a live Bluetooth advertising preflight check and fails fast on Raspberry Pi kernel `6.12.93*` and affected `6.18.*` builds, which are known to break BlueZ D-Bus BLE advertising.

For field power saving, disable Wi-Fi after testing is complete:

```bash
sudo DISABLE_WIFI=1 ./scripts/install.sh
```

The initializer does not reboot automatically. Reboot after initialization before field testing:

```bash
sudo reboot
```

## Audio Files

The default config expects:

```text
/opt/sculpture/siren-app/assets/audio/siren-30.wav
```

Large audio files are ignored by Git. Copy them with `scp`, rsync, a USB drive, Git LFS, or a GitHub Release asset.

Test playback:

```bash
/opt/sculpture/siren-app/scripts/test-audio.sh
```

## Shared BLE Gateway

The siren app owns one BLE advertisement and one GATT server:

```text
sculpture-ble-control.service
```

That gateway registers one shared service UUID with separate provisioning and
sculpture command/status characteristics. Their command handlers and response
state remain independent. There is no separate provisioning daemon.

The sculpture characteristics accept:

```text
testing_mode
sculpture_mode
test_play
test_pause
test_restart
play_sculpture
pause_sculpture
set_playback_window
clear_playback_window
set_volume
status
network_status
set_wifi_power
wifi_power_status
diagnostics
reboot
```

Sculpture mode is the normal field mode: playback follows the runtime playback window, and `play_sculpture` / `pause_sculpture` control that normal playback. Testing mode is the manual field-test mode: `test_play`, `test_pause`, and `test_restart` let you exercise audio playback without returning immediately to normal autoplay.

`set_playback_window` accepts `start_time` and `stop_time` in `HH:MM` format, for example `08:00` to `21:00`. The window is stored in `/var/lib/sculpture/playback-window.json`. If no playback window is set, sculpture mode does not autoplay. `clear_playback_window` disables sculpture-mode autoplay again. `set_volume` accepts `volume_percent` from 0 to 100.

The `diagnostics` command returns compact service states and recent warnings for light field debugging over Bluetooth.

`set_wifi_power` accepts an `enabled` boolean and changes Wi-Fi power in a
background worker so BLE requests remain responsive. Poll `wifi_power_status`
until it returns `success` or `error`. Turning Wi-Fi off disconnects SSH and
other network access, but does not disable the Bluetooth control service.

The shared BLE service UUID is configured in
`siren-app/config/sculpture.yaml`; the sibling provisioning config uses the
same UUID. By default, `ble.control.device_name: "device"` makes the
advertised Bluetooth name use the Pi hostname. Names are sanitized and
truncated to 8 UTF-8 bytes for more reliable Raspberry Pi BLE advertising with
a 128-bit service UUID.

Bluetooth preflight and debug commands:

```bash
sudo /opt/sculpture/scripts/check-bluetooth-preflight.sh
sudo systemctl status bluetooth.service --no-pager
sudo systemctl status sculpture-ble-control.service --no-pager
sudo journalctl -u sculpture-ble-control.service -b -n 100 --no-pager
```

## Services and Logs

```bash
sudo systemctl status bluetooth.service
sudo systemctl status sculpture-audio.service
sudo systemctl status sculpture-healthcheck.timer
sudo systemctl status sculpture-wittypi-clock-sync.timer
sudo systemctl status sculpture-ble-control.service
sudo journalctl -u sculpture-audio.service -b -n 100 --no-pager
sudo journalctl -u sculpture-ble-control.service -b -n 100 --no-pager
```

To stop and disable sculpture-related services during debugging:

```bash
sudo ./scripts/disable-services.sh
```

This disables current sculpture services plus Witty Pi/UWI services for low-level debugging. By default it leaves core `bluetooth.service` and `NetworkManager.service` alone. Disable them only when intentionally testing a fully quiet system:

```bash
sudo INCLUDE_BLUETOOTH=1 INCLUDE_NETWORK_MANAGER=1 ./scripts/disable-services.sh
```

Services write to the systemd journal instead of separate application log files. Follow live audio logs with:

```bash
sudo journalctl -u sculpture-audio.service -f
```

Run `sudo ./scripts/backup-logs.sh` to export the available sculpture service journals to a compressed file under `/opt/sculpture/log-backups`.

## Install Updates

Script naming in this repo separates first-time machine setup from normal app updates:

- `scripts/initialize-pi.sh`: one-time Pi provisioning for packages, Witty Pi, audio, Bluetooth, and systemd.
- `scripts/install.sh`: recurring app install/update after code has already been copied to the Pi.
- `../sync-to-pi.sh`: laptop-side rsync helper that copies both application folders to the Pi and optionally initializes or installs the Pi-side services.

On an existing Pi checkout:

```bash
cd /opt/sculpture
sudo ./scripts/install.sh
```

From the shared project root, run:

```bash
./sync-to-pi.sh
```

The sync script reads connection defaults from `sync.env`, prompts for the Pi
hostname or IP address, and copies both monorepo application directories into
`/opt/sculpture`. It then prompts whether to initialize a fresh Pi and whether
to install and restart services. Both action prompts default to `no`; answer
`no` to both for a copy-only sync.

Audio syncing can still be overridden for a single run:

```bash
SYNC_AUDIO=0 ./sync-to-pi.sh  # Skip large local audio files.
```

## Witty Pi Power Policy

The default deployment keeps the sculpture on continuously whenever external
power is available. It clears Witty Pi startup and shutdown alarms, removes the
installed schedule script, and sets the Witty Pi hardware to `Default ON` so
connecting external power boots the Pi. The RTC continues keeping time through
power interruptions.

The vendor installer automatically installs UUGear Web Interface (UWI), which starts a local web server. This project runs the standard Witty Pi installer through `siren-app/scripts/install-wittypi.sh`, then disables the `uwi` service so the web interface is available for manual maintenance but does not run in the field.

The Python audio service also checks the configured active window, but that is a playback guard, not the primary power scheduler.

When Sculpture Mode playback starts or resumes, audio begins immediately and
then restarts once at a five-minute wall-clock boundary. A two-minute lead time
gives an operator time to start the other sculptures: 17:08:01 through 17:13:00
maps to 17:15, while a start just after 17:13 maps to 17:20. This gives
sculptures with synchronized RTCs a common playback origin without requiring a
network connection. Testing Mode is not synchronized. Configure the interval
and lead time with `audio.sculpture_sync_interval_seconds` and
`audio.sculpture_sync_lead_time_seconds` in `sculpture.yaml`; the defaults are
300 and 120 seconds.

The installer patches the vendor daemon's clock decision without replacing the
standard Witty Pi installation. A valid RTC initializes system time at boot. An
invalid RTC remains untouched until operating-system NTP reports confirmed
synchronization; only then does `sculpture-wittypi-clock-sync.timer` write the
corrected system time to the RTC. Scheduled Sculpture Mode playback is disabled
while `/run/sculpture-clock-trusted` is absent, but manual Testing Mode remains
available.

Clock safety is independent of Witty Pi power scheduling. Setting
`APPLY_WITTYPI_SCHEDULE=0` leaves the RTC patch and synchronization timer enabled.
Set `ENABLE_WITTYPI_CLOCK_SYNC=0` only when intentionally disabling Witty Pi clock
integration as well.

The tracked schedule placeholder is:

```text
siren-app/config/wittypi/schedule.wpi
```

To intentionally restore power scheduling, add an active Witty Pi schedule to
that file and deploy with `ENABLE_WITTYPI_POWER_SCHEDULE=1`. Reboot after
applying Witty Pi changes so the daemon loads the power policy cleanly.

Bluetooth note: the standard Witty Pi installer applies `dtoverlay=miniuart-bt`. On Raspberry Pi models with onboard Bluetooth, that moves Bluetooth to the mini UART so GPIO14/TXD can behave the way Witty Pi expects for shutdown/power-cut signaling. The tradeoff is that Bluetooth can become more sensitive to UART/core clock behavior, so BLE control should be retested after the first Witty Pi install and reboot.

## Configuration

The app loads:

```text
/opt/sculpture/siren-app/config/sculpture.yaml
```

Override this path for testing or custom deployment:

```bash
SCULPTURE_CONFIG=/path/to/sculpture.yaml
```

## Development Checks

The code targets Python 3.9+.

```bash
python -m pytest
python -m compileall siren-app tests
bash -n scripts/*.sh
```

## Field Maintenance Checklist

Before installation:

- Confirm audio plays through amp.
- Confirm BLE siren control works from your hosted Web Bluetooth page.
- Confirm system time and Witty Pi RTC are correct.
- Confirm Witty Pi morning/evening schedule.
- Confirm low-voltage behavior if used.
- Confirm Pi recovers after power interruption.
- Confirm logs are being written.
- Clone the working SD card.
- Keep at least one spare SD card with the maintenance kit.
