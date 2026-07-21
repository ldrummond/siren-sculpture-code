(() => {
  'use strict';

  const scriptUrl = new URL(document.currentScript.src, window.location.href);
  const siteRoot = new URL('./', scriptUrl);
  const isIOS = /iPad|iPhone|iPod/.test(navigator.userAgent)
    || (navigator.platform === 'MacIntel' && navigator.maxTouchPoints > 1);
  const isAndroid = /Android/i.test(navigator.userAgent);

  function siteUrl(path) {
    return new URL(path, siteRoot).href;
  }

  async function removeLegacyPWA() {
    if ('serviceWorker' in navigator) {
      const registrations = await navigator.serviceWorker.getRegistrations();
      await Promise.all(
        registrations
          .filter((registration) => registration.scope === siteRoot.href)
          .map((registration) => registration.unregister())
      );
    }
    if ('caches' in window) {
      const cacheNames = await caches.keys();
      await Promise.all(
        cacheNames
          .filter((name) => name.startsWith('siren-controller-'))
          .map((name) => caches.delete(name))
      );
    }
  }

  function addNavigation() {
    const routes = [
      ['Home', ''],
      ['Sculpture', 'siren-sculpture-code/web-bluetooth/siren-control.html'],
      ['Wi-Fi', 'rpi-ble-wifi-provisioning/web-bluetooth/provisioning.html']
    ];
    const currentPath = new URL(window.location.href).pathname.replace(/\/$/, '/index.html');
    const navigation = document.createElement('nav');
    navigation.className = 'site-nav';
    navigation.setAttribute('aria-label', 'Siren controller');
    for (const [label, path] of routes) {
      const link = document.createElement('a');
      link.href = siteUrl(path);
      link.textContent = label;
      const routePath = new URL(link.href).pathname.replace(/\/$/, '/index.html');
      if (routePath === currentPath) link.setAttribute('aria-current', 'page');
      navigation.append(link);
    }
    document.body.prepend(navigation);
  }

  function chromeIntentFor(url) {
    const target = new URL(url);
    const scheme = target.protocol.replace(':', '');
    const path = `${target.host}${target.pathname}${target.search}`;
    const fallback = encodeURIComponent('https://play.google.com/store/apps/details?id=com.android.chrome');
    return `intent://${path}#Intent;scheme=${scheme};package=com.android.chrome;S.browser_fallback_url=${fallback};end`;
  }

  function showMobileBrowserGate() {
    if ('bluetooth' in navigator || (!isIOS && !isAndroid)) return;
    document.body.classList.add('browser-unsupported');
    const gate = document.createElement('div');
    gate.className = 'browser-gate';
    gate.setAttribute('role', 'dialog');
    gate.setAttribute('aria-modal', 'true');

    if (isIOS) {
      gate.setAttribute('aria-labelledby', 'browser-gate-title');
      gate.innerHTML = `
        <div class="browser-gate-card">
          <h1 id="browser-gate-title">Open this page in Bluefy</h1>
          <p>This iPhone or iPad browser does not support Web Bluetooth. Install Bluefy, then paste and open this same page address inside the Bluefy app.</p>
          <div class="browser-actions">
            <a class="browser-action" href="https://apps.apple.com/app/bluefy-web-ble-browser/id1492822055">Get Bluefy from the App Store</a>
            <button class="browser-action secondary" id="copyPageUrl" type="button">Copy page link</button>
          </div>
          <p class="browser-copy-status" id="copyPageStatus" role="status" aria-live="polite"></p>
        </div>`;
      document.body.append(gate);
      gate.querySelector('#copyPageUrl').addEventListener('click', async () => {
        const status = gate.querySelector('#copyPageStatus');
        try {
          await navigator.clipboard.writeText(window.location.href);
          status.textContent = 'Page link copied. Paste it into Bluefy.';
        } catch (error) {
          status.textContent = `Copy this address into Bluefy: ${window.location.href}`;
        }
      });
      return;
    }

    gate.setAttribute('aria-labelledby', 'browser-gate-title');
    gate.innerHTML = `
      <div class="browser-gate-card">
        <h1 id="browser-gate-title">Open this page in Chrome</h1>
        <p>This Android browser does not support Web Bluetooth. Reopen this same page in Google Chrome for Android.</p>
        <div class="browser-actions">
          <a class="browser-action" href="${chromeIntentFor(window.location.href)}">Open in Chrome</a>
        </div>
      </div>`;
    document.body.append(gate);
  }

  function showDesktopWarning() {
    if ('bluetooth' in navigator || isIOS || isAndroid) return;
    const warning = document.createElement('p');
    warning.className = 'browser-warning';
    warning.textContent = 'This browser does not provide Web Bluetooth. Use Chrome or Edge over HTTPS.';
    document.querySelector('.site-nav').after(warning);
  }

  addNavigation();
  showMobileBrowserGate();
  showDesktopWarning();
  removeLegacyPWA().catch((error) => console.warn('Unable to remove the previous web app cache', error));
})();
