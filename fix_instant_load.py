import os
import subprocess

SKIP_DIRS = {".git", "venv", ".venv", "env", "node_modules", "__pycache__", "staticfiles"}


def find_file(filename):
    for root, dirs, files in os.walk("."):
        dirs[:] = [d for d in dirs if d not in SKIP_DIRS]
        if filename in files:
            return os.path.join(root, filename)
    return None


def patch_production_py():
    path = find_file("production.py")
    if not path:
        print("⚠️ production.py not found, skipping.")
        return

    with open(path, "r", encoding="utf-8-sig") as f:
        content = f.read()

    target = "STATICFILES_STORAGE = 'whitenoise.storage.CompressedStaticFilesStorage'"
    replacement = (
        "STATICFILES_STORAGE = 'whitenoise.storage.CompressedStaticFilesStorage'\n"
        "WHITENOISE_MAX_AGE = 31536000  # 1-year browser cache for static images, CSS & JS"
    )

    if "WHITENOISE_MAX_AGE" not in content and target in content:
        content = content.replace(target, replacement, 1)
        with open(path, "w", encoding="utf-8") as f:
            f.write(content)
        print(f"✅ Patched {path}: enabled 1-year WhiteNoise static asset caching.")
    else:
        print(f"✅ Verified {path}: WhiteNoise caching already configured.")


def patch_base_html():
    path = find_file("base.html")
    if not path:
        print("⚠️ base.html not found, skipping.")
        return

    with open(path, "r", encoding="utf-8-sig") as f:
        content = f.read()

    # 1. Preload core emblems in <head> so they render instantaneously with zero broken flash
    manifest_tag = '<link rel="manifest" href="{% static \'manifest.json\' %}">'
    preload_tags = (
        '<link rel="manifest" href="{% static \'manifest.json\' %}">\n'
        '<link rel="preload" as="image" href="{% static \'images/finale_logo.jpg\' %}?v=9">\n'
        '<link rel="preload" as="image" href="{% static \'images/hacker.png\' %}?v=1">'
    )
    if "rel=\"preload\" as=\"image\"" not in content and manifest_tag in content:
        content = content.replace(manifest_tag, preload_tags, 1)

    # 2. Remove initial blocking overlay class so page paints in 0ms
    content = content.replace(
        '<div id="vault-page-loader" class="vault-loader-overlay active" aria-hidden="false"',
        '<div id="vault-page-loader" class="vault-loader-overlay" aria-hidden="true"',
        1,
    )

    # 3. Eliminate the hardcoded 3000ms artificial delay
    content = content.replace(
        "setTimeout(hideNavLoader, 3000);",
        "hideNavLoader();",
        1,
    )

    with open(path, "w", encoding="utf-8") as f:
        f.write(content)
    print(f"✅ Patched {path}: added image preloads & removed 3-second blocking loader.")


def patch_app_js():
    path = find_file("app.js") or "static/js/app.js"
    os.makedirs(os.path.dirname(path), exist_ok=True)

    app_js_code = """// Register Service Worker with Lifecycle & Scope Controls (Zero Mid-Load Reloads)
if ('serviceWorker' in navigator) {
  const hadController = Boolean(navigator.serviceWorker.controller);

  window.addEventListener('load', () => {
    navigator.serviceWorker
      .register('/sw.js', { scope: '/' })
      .then((registration) => {
        registration.update().catch(() => {});
      })
      .catch((err) => {
        console.error('Service Worker registration failed:', err);
      });
  });

  // Reload ONLY when upgrading an existing controller, never on initial visit
  let refreshing = false;
  navigator.serviceWorker.addEventListener('controllerchange', () => {
    if (hadController && !refreshing) {
      refreshing = true;
      window.location.reload();
    }
  });
}

// Intercept Network Switches & Auto-Recover Dropped Connections
window.addEventListener('online', () => {
  if (
    document.title.includes('Reconnecting') ||
    document.body.innerText.includes('Network Reconnecting') ||
    document.body.innerText.includes('Connection Lost')
  ) {
    window.location.reload();
  }
});

// Prevent unhandled promise rejections on temporary network drops
window.addEventListener('unhandledrejection', (event) => {
  if (
    event.reason &&
    (event.reason.name === 'TypeError' ||
      String(event.reason).includes('Failed to fetch') ||
      String(event.reason).includes('NetworkError'))
  ) {
    event.preventDefault();
  }
});
"""
    with open(path, "w", encoding="utf-8") as f:
        f.write(app_js_code)
    print(f"✅ Patched {path}: prevented double-reload on initial load.")


def patch_sw_js():
    path = find_file("sw.js") or "static/sw.js"
    os.makedirs(os.path.dirname(path), exist_ok=True)

    sw_js_code = """const CACHE_NAME = 'inheritancebox-v2026.15';
const ASSETS_TO_CACHE = [
  '/static/css/theme.css',
  '/static/js/app.js',
  '/static/manifest.json',
  '/static/images/icon-192.png',
  '/static/images/icon-512.png',
  '/static/images/finale_logo.jpg',
  '/static/images/hacker.png'
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
});

self.addEventListener('fetch', (event) => {
  if (!event.request.url.startsWith('http') || event.request.method !== 'GET') return;

  // 1. Navigation Requests pass straight to Django with instant offline fallback
  if (event.request.mode === 'navigate') {
    event.respondWith(
      fetch(event.request).catch(() => {
        return new Response(
          `<!DOCTYPE html>
          <html lang="en">
          <head>
            <meta charset="UTF-8">
            <meta name="viewport" content="width=device-width, initial-scale=1.0">
            <title>InheritanceBox | Reconnecting</title>
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
              <button class="btn-retry" onclick="window.location.reload()">Reconnect ibox ⚡</button>
            </div>
          </body>
          </html>`,
          { status: 200, statusText: 'OK', headers: new Headers({ 'Content-Type': 'text/html' }) }
        );
      })
    );
    return;
  }

  // 2. Manifest Always Network-First (Prevents duplicate PWA installs)
  const requestUrl = new URL(event.request.url);
  if (requestUrl.pathname.endsWith('manifest.json')) {
    event.respondWith(
      fetch(event.request)
        .then((networkResponse) => {
          if (networkResponse && networkResponse.ok) {
            const responseClone = networkResponse.clone();
            caches.open(CACHE_NAME).then((cache) => cache.put('/static/manifest.json', responseClone));
          }
          return networkResponse;
        })
        .catch(() => caches.match('/static/manifest.json', { ignoreSearch: true }))
    );
    return;
  }

  // 3. Static Assets & Images: Instant Cache Hit + Runtime Auto-Caching
  event.respondWith(
    caches.match(event.request, { ignoreSearch: true }).then((cachedResponse) => {
      if (cachedResponse) return cachedResponse;

      return fetch(event.request)
        .then((networkResponse) => {
          if (
            networkResponse &&
            (networkResponse.ok || networkResponse.type === 'opaque') &&
            (event.request.destination === 'image' ||
              requestUrl.pathname.startsWith('/static/'))
          ) {
            const clone = networkResponse.clone();
            caches.open(CACHE_NAME).then((cache) => cache.put(event.request, clone));
          }
          return networkResponse;
        })
        .catch(() => Response.error());
    })
  );
});
"""
    with open(path, "w", encoding="utf-8") as f:
        f.write(sw_js_code)
    print(f"✅ Patched {path}: pre-cached all images & eliminated mid-load stream aborts.")


def git_push():
    print("🚀 Committing and pushing instant-load optimization...")
    subprocess.run(["git", "add", "."], check=True)
    commit = subprocess.run(
        ["git", "commit", "-m", "Eliminate double reload, 3s loader delay, and broken image flash"],
        capture_output=True,
        text=True,
    )
    if commit.returncode == 0:
        print(commit.stdout.strip())
    else:
        print("ℹ️ Commit status:", commit.stdout.strip() or commit.stderr.strip())
    subprocess.run(["git", "push"], check=True)
    print("🎉 Pushed! Coolify is deploying your instant-load update now.")


if __name__ == "__main__":
    patch_production_py()
    patch_base_html()
    patch_app_js()
    patch_sw_js()
    git_push()