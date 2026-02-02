const CACHE_NAME = 'myway-v2'; // Incremented version
const urlsToCache = [
  '/',
  '/static/manifest.json',
  '/static/icon-192.png',
  'https://fonts.googleapis.com/css2?family=Plus+Jakarta+Sans:wght@400;700;800&family=JetBrains+Mono:wght@500;700&display=swap'
];
self.addEventListener('install', event => {
  event.waitUntil(
    caches.open(CACHE_NAME).then(cache => {
      // Use 'add' for these essentials to ensure they are present
      return cache.addAll(urlsToCache);
    })
  );
});

self.addEventListener('fetch', event => {
  event.respondWith(
    // Try network first, fall back to cache if offline
    fetch(event.request).catch(() => caches.match(event.request))
  );
});