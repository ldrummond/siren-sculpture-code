(() => {
  'use strict';

  const scriptUrl = new URL(document.currentScript.src, window.location.href);
  const appRoot = new URL('./', scriptUrl);
  const isIOS = /iPad|iPhone|iPod/.test(navigator.userAgent)
    || (navigator.platform === 'MacIntel' && navigator.maxTouchPoints > 1);
  const isStandalone = window.matchMedia('(display-mode: standalone)').matches
    || navigator.standalone === true;
  let deferredInstallPrompt = null;

  function appUrl(path) {
    return new URL(path, appRoot).href;
  }

  function addNavigation() {
    if (document.querySelector('.pwa-site-nav')) return;
    const routes = [
      ['Home', ''],
      ['Sculpture', 'siren-sculpture-code/web-bluetooth/siren-control.html'],
      ['Wi-Fi', 'rpi-ble-wifi-provisioning/web-bluetooth/provisioning.html']
    ];
    const currentPath = new URL(window.location.href).pathname.replace(/\/$/, '/index.html');
    const navigation = document.createElement('nav');
    navigation.className = 'pwa-site-nav';
    navigation.setAttribute('aria-label', 'Siren controller');
    for (const [label, path] of routes) {
      const link = document.createElement('a');
      link.href = appUrl(path);
      link.textContent = label;
      const routePath = new URL(link.href).pathname.replace(/\/$/, '/index.html');
      if (routePath === currentPath) link.setAttribute('aria-current', 'page');
      navigation.append(link);
    }
    document.body.prepend(navigation);
  }

  function showBluetoothWarning() {
    if ('bluetooth' in navigator || document.querySelector('.pwa-browser-warning')) return;
    const warning = document.createElement('p');
    warning.className = 'pwa-browser-warning';
    warning.textContent = isIOS
      ? 'This iOS browser does not provide Web Bluetooth. Installing the web app does not add Bluetooth support.'
      : 'This browser does not provide Web Bluetooth. Use a compatible browser over HTTPS.';
    const navigation = document.querySelector('.pwa-site-nav');
    navigation ? navigation.after(warning) : document.body.prepend(warning);
  }

  function showIOSInstallGate() {
    if (!isIOS || isStandalone || document.querySelector('.pwa-install-gate')) return;
    document.body.classList.add('pwa-install-required');
    const gate = document.createElement('div');
    gate.className = 'pwa-install-gate';
    gate.setAttribute('role', 'dialog');
    gate.setAttribute('aria-modal', 'true');
    gate.setAttribute('aria-labelledby', 'pwa-install-title');
    gate.innerHTML = `
      <div class="pwa-install-card">
        <h1 id="pwa-install-title">To use this website on your phone you must install it as a web app</h1>
        <p>Install Siren Control from your browser's sharing menu, then open it from your Home Screen.</p>
        ${'bluetooth' in navigator ? '' : '<p><strong>Important:</strong> this iOS browser does not provide Web Bluetooth, and installing the web app will not add Bluetooth support.</p>'}
        <button id="pwaInstallButton" type="button">Install</button>
        <div id="pwaInstallSteps" class="pwa-install-steps" hidden>
          <p><strong>On iPhone or iPad:</strong> tap the Share button, choose <strong>Add to Home Screen</strong>, then tap <strong>Add</strong>. Open Siren Control from the new Home Screen icon.</p>
          <p>iOS does not allow a website to open the installation prompt directly.</p>
        </div>
      </div>`;
    document.body.append(gate);
    gate.querySelector('#pwaInstallButton').addEventListener('click', () => {
      gate.querySelector('#pwaInstallSteps').hidden = false;
      gate.querySelector('#pwaInstallButton').hidden = true;
    });
  }

  async function installApp() {
    if (!deferredInstallPrompt) return;
    deferredInstallPrompt.prompt();
    await deferredInstallPrompt.userChoice;
    deferredInstallPrompt = null;
    document.querySelector('#installAppButton')?.classList.remove('available');
  }

  window.addEventListener('beforeinstallprompt', (event) => {
    event.preventDefault();
    deferredInstallPrompt = event;
    const button = document.querySelector('#installAppButton');
    if (button) button.classList.add('available');
  });

  document.querySelector('#installAppButton')?.addEventListener('click', installApp);
  addNavigation();
  showBluetoothWarning();
  showIOSInstallGate();

  if ('serviceWorker' in navigator && window.isSecureContext) {
    navigator.serviceWorker.register(appUrl('service-worker.js')).catch((error) => {
      console.warn('Unable to register the Siren Controller service worker', error);
    });
  }
})();
