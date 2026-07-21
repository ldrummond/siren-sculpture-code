const CACHE_NAME = 'siren-controller-v1';
const APP_ASSETS = [
  './',
  './index.html',
  './manifest.webmanifest',
  './pwa.css',
  './pwa.js',
  './icons/siren-controller.svg',
  './icons/siren-controller-192.png',
  './icons/siren-controller-512.png',
  './siren-sculpture-code/web-bluetooth/siren-control.html',
  './rpi-ble-wifi-provisioning/web-bluetooth/provisioning.html'
];

self.addEventListener('install', (event) => {
  event.waitUntil(caches.open(CACHE_NAME).then((cache) => cache.addAll(APP_ASSETS)));
  self.skipWaiting();
});

self.addEventListener('activate', (event) => {
  event.waitUntil(
    caches.keys()
      .then((names) => Promise.all(names.filter((name) => name !== CACHE_NAME).map((name) => caches.delete(name))))
      .then(() => self.clients.claim())
  );
});

self.addEventListener('fetch', (event) => {
  if (event.request.method !== 'GET' || new URL(event.request.url).origin !== self.location.origin) return;

  if (event.request.mode === 'navigate') {
    event.respondWith(
      fetch(event.request)
        .then((response) => {
          const copy = response.clone();
          caches.open(CACHE_NAME).then((cache) => cache.put(event.request, copy));
          return response;
        })
        .catch(() => caches.match(event.request).then((response) => response || caches.match('./index.html')))
    );
    return;
  }

  event.respondWith(caches.match(event.request).then((response) => response || fetch(event.request)));
});
