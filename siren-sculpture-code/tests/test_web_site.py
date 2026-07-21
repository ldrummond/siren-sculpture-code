from pathlib import Path


PROJECT_ROOT = Path(__file__).parents[2]
CONTROL_PAGE = PROJECT_ROOT / "siren-sculpture-code" / "web-bluetooth" / "siren-control.html"
WIFI_PAGE = PROJECT_ROOT / "rpi-ble-wifi-provisioning" / "web-bluetooth" / "provisioning.html"


def test_both_controllers_load_shared_site_assets() -> None:
    for page in (CONTROL_PAGE, WIFI_PAGE):
        html = page.read_text()
        assert 'rel="manifest"' not in html
        assert '<script src="../../site.js"></script>' in html
        assert 'href="../../site.css"' in html


def test_mobile_browser_guidance_is_present_without_pwa_installation() -> None:
    script = (PROJECT_ROOT / "site.js").read_text()

    assert "Open this page in Bluefy" in script
    assert "id1492822055" in script
    assert "Copy page link" in script
    assert "Open this page in Chrome" in script
    assert "package=com.android.chrome" in script
    assert "'bluetooth' in navigator" in script
    assert "registration.unregister()" in script
    assert "name.startsWith('siren-controller-')" in script
    assert not (PROJECT_ROOT / "manifest.webmanifest").exists()
    assert not (PROJECT_ROOT / "service-worker.js").exists()
