import json
from pathlib import Path


PROJECT_ROOT = Path(__file__).parents[2]
CONTROL_PAGE = PROJECT_ROOT / "siren-sculpture-code" / "web-bluetooth" / "siren-control.html"
WIFI_PAGE = PROJECT_ROOT / "rpi-ble-wifi-provisioning" / "web-bluetooth" / "provisioning.html"


def test_single_pwa_contains_both_bluetooth_controllers() -> None:
    manifest = json.loads((PROJECT_ROOT / "manifest.webmanifest").read_text())
    shortcut_urls = {shortcut["url"] for shortcut in manifest["shortcuts"]}

    assert manifest["start_url"] == "./"
    assert manifest["scope"] == "./"
    assert "./siren-sculpture-code/web-bluetooth/siren-control.html" in shortcut_urls
    assert "./rpi-ble-wifi-provisioning/web-bluetooth/provisioning.html" in shortcut_urls


def test_both_controllers_load_shared_pwa_assets() -> None:
    for page in (CONTROL_PAGE, WIFI_PAGE):
        html = page.read_text()
        assert 'rel="manifest" href="../../manifest.webmanifest"' in html
        assert '<script src="../../pwa.js"></script>' in html
        assert 'href="../../pwa.css"' in html


def test_ios_install_gate_and_offline_assets_are_present() -> None:
    script = (PROJECT_ROOT / "pwa.js").read_text()
    service_worker = (PROJECT_ROOT / "service-worker.js").read_text()

    assert "To use this website on your phone you must install it as a web app" in script
    assert "Add to Home Screen" in script
    assert "navigator.standalone === true" in script
    assert "'bluetooth' in navigator" in script
    assert "siren-control.html" in service_worker
    assert "provisioning.html" in service_worker
