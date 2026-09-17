const CACHE_NAME = 'legacytrace-v5';
const ASSETS_TO_CACHE = [
  '/',
  '/static/css/theme.css',
  '/static/js/app.js',
  '/static/manifest.json'
];

// Helper: Safely retry transient cellular & radio drops by URL without stream lockups
async function fetchWithNetworkRetry(request, maxRetries = 3, delay = 400) {
  for (let attempt = 0; attempt <= maxRetries; attempt++) {
    try {
      if (request.method === 'GET') {
        return await fetch(request.url, {
          method: 'GET',
          headers: request.headers,
          credentials: request.credentials,
          mode: request.mode
        });
      }
      return await fetch(request.clone());
    } catch (error) {
      if (attempt === maxRetries) throw error;
      // Exponential backoff to ride out mobile antenna IP re-negotiation
      await new Promise((resolve) => setTimeout(resolve, delay * (attempt + 1)));
    }
  }
}

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
  if (!event.request.url.startsWith('http')) return;

  // 1. Navigation Requests (Page Changes & Deep Links)
  if (event.request.mode === 'navigate') {
    event.respondWith(
      fetchWithNetworkRetry(event.request, 3, 400)
        .then((networkResponse) => {
          if (networkResponse && networkResponse.status === 200 && event.request.method === 'GET') {
            const responseClone = networkResponse.clone();
            caches.open(CACHE_NAME).then((cache) => cache.put(event.request, responseClone));
          }
          return networkResponse;
        })
        .catch(async () => {
          const cache = await caches.open(CACHE_NAME);

          const cachedResponse = await cache.match(event.request);
          if (cachedResponse) return cachedResponse;

          const rootShell = await cache.match('/');
          if (rootShell) return rootShell;

          // Always return status 200 to prevent Chromium from aborting to ERR_NETWORK_CHANGED
          return new Response(
            `<!DOCTYPE html>
            <html lang="en">
            <head>
              <meta charset="UTF-8">
              <meta name="viewport" content="width=device-width, initial-scale=1.0">
              <title>LegacyTrace | Reconnecting</title>
              <style>
                body {
                  font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
                  text-align: center;
                  padding: 2.5rem 1.25rem;
                  background: #0A192F;
                  color: #ffffff;
                  display: flex;
                  flex-direction: column;
                  align-items: center;
                  justify-content: center;
                  min-height: 80vh;
                  margin: 0;
                }
                .offline-card {
                  background: radial-gradient(circle at 10% 20%, #07162c 0%, #020c1b 100%);
                  border: 1.5px solid rgba(6, 182, 212, 0.4);
                  border-radius: 20px;
                  padding: 2rem 1.5rem;
                  max-width: 380px;
                  box-shadow: 0 16px 36px rgba(2, 12, 27, 0.5);
                }
                h2 { margin: 0.5rem 0 0.35rem; font-size: 1.35rem; font-weight: 900; }
                p { font-size: 0.85rem; color: #94A3B8; line-height: 1.55; margin-bottom: 1.5rem; }
                .btn-retry {
                  background: linear-gradient(135deg, #0284c7 0%, #06b6d4 100%);
                  color: #ffffff;
                  border: none;
                  padding: 0.85rem 1.6rem;
                  border-radius: 12px;
                  font-size: 0.95rem;
                  font-weight: 800;
                  cursor: pointer;
                  box-shadow: 0 4px 15px rgba(6, 182, 212, 0.35);
                  width: 100%;
                }
              </style>
            </head>
            <body>
              <div class="offline-card">
                <div style="font-size: 2.5rem; margin-bottom: 0.5rem;">📡</div>
                <h2>Network Reconnecting</h2>
                <p>A cellular connection shift interrupted the page. Tap below to resume.</p>
                <button class="btn-retry" onclick="window.location.reload()">Reconnect Vault ⚡</button>
              </div>
            </body>
            </html>`,
            {
              status: 200,
              statusText: 'OK',
              headers: new Headers({ 'Content-Type': 'text/html' })
            }
          );
        })
    );
    return;
  }

  // 2. Static Resources (CSS, Scripts, Icons, Fonts)
  event.respondWith(
    caches.match(event.request).then((cachedResponse) => {
      if (cachedResponse) return cachedResponse;
      return fetch(event.request).catch(() => {});
    })
  );
});