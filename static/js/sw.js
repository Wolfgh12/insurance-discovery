const CACHE_NAME = 'legacytrace-v3';
const ASSETS_TO_CACHE = [
  '/',
  '/static/css/theme.css',
  '/static/js/app.js',
  '/static/manifest.json'
];

self.addEventListener('install', (event) => {
  event.waitUntil(
    caches.open(CACHE_NAME).then((cache) => {
      return Promise.allSettled(
        ASSETS_TO_CACHE.map((asset) =>
          cache.add(asset).catch((err) => console.warn(`Failed to cache ${asset}:`, err))
        )
      );
    })
  );
  self.skipWaiting();
});

self.addEventListener('activate', (event) => {
  event.waitUntil(
    caches.keys().then((cacheNames) => {
      return Promise.all(
        cacheNames.map((cache) => {
          if (cache !== CACHE_NAME) {
            return caches.delete(cache);
          }
        })
      );
    })
  );
  self.clients.claim();
});

self.addEventListener('fetch', (event) => {
  // Only handle HTTP/HTTPS requests
  if (!event.request.url.startsWith('http')) return;

  if (event.request.mode === 'navigate') {
    event.respondWith(
      fetch(event.request).catch(async () => {
        const cache = await caches.open(CACHE_NAME);
        const cachedResponse = await cache.match(event.request);
        if (cachedResponse) return cachedResponse;

        // Fallback to cached home shell if specific route isn't cached
        const rootShell = await cache.match('/');
        if (rootShell) return rootShell;

        // Final safety net: never return undefined to event.respondWith
        return new Response(
          '<!DOCTYPE html><html><body style="font-family:sans-serif;text-align:center;padding:50px;background:#0A192F;color:#fff;"><h2>Connection Lost</h2><p>Please check your internet connection and try again.</p><button onclick="location.reload()" style="padding:10px 20px;border-radius:6px;border:none;background:#2563EB;color:#fff;cursor:pointer;">Retry</button></body></html>',
          {
            status: 503,
            statusText: 'Service Unavailable',
            headers: new Headers({ 'Content-Type': 'text/html' })
          }
        );
      })
    );
    return;
  }

  // Non-navigation requests (CSS, JS, images, API calls)
  event.respondWith(
    caches.match(event.request).then((cachedResponse) => {
      return cachedResponse || fetch(event.request);
    })
  );
});