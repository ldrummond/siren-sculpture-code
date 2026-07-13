#!/usr/bin/env bash
set -euo pipefail

cat <<'MSG'
This project intentionally does not automate SD-card imaging yet.

Recommended field process:
1. Install and verify the controller on the target Raspberry Pi.
2. Shut the Pi down cleanly.
3. Clone the SD card from a maintenance workstation.
4. Label one working card and at least one spare.
MSG
