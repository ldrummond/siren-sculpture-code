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
- `sync-on-pi.sh`: performs the same deployment from a Git checkout already on
  the Pi, without SSH.
- `pi-status.sh`: prints relevant service statuses from the Pi.
- `sync.env.example`: template for local SSH and deployment defaults.
- `index.html`, `site.js`, and `site.css`: the unified Web Bluetooth controller
  site for GitHub Pages.

## Web Bluetooth controller site

Publish the repository root with GitHub Pages. The root `index.html` is the
single entry point for sculpture control and Wi-Fi provisioning, and both
controller pages share one navigation and browser-compatibility layer. If Web
Bluetooth is unavailable on iPhone or iPad, the site directs the user to Bluefy
and provides a button to copy the current page address. Unsupported Android
browsers provide a button that reopens the same address in Chrome.

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

## On-device deployment

If this repository is cloned directly onto the Pi, update the checkout and
deploy it with:

```bash
git pull --ff-only
git lfs pull
./sync-on-pi.sh
```

`sync-on-pi.sh` copies `siren-sculpture-code/` to `/opt/sculpture` and
`rpi-ble-wifi-provisioning/` to
`/opt/sculpture/vendor/rpi-ble-wifi-provisioning`, then presents the same
initializer and installer prompts as `sync-to-pi.sh`. Clone the repository
outside `/opt/sculpture` so the Git checkout remains separate from the deployed
runtime files.

Audio files are tracked through Git LFS and are always included when the
hydrated checkout is copied into `/opt/sculpture`. The Pi initializer and
installer install Git LFS and initialize it for the sculpture user.
