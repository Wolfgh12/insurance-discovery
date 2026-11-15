import glob
import json
import os
import re
import subprocess
from PIL import Image

SKIP_DIRS = {".git", "venv", ".venv", "env", "node_modules", "__pycache__", "staticfiles"}


def find_project_files(target_names):
    found = {name: [] for name in target_names}
    for root, dirs, files in os.walk("."):
        dirs[:] = [d for d in dirs if d not in SKIP_DIRS]
        for f in files:
            if f in found:
                found[f].append(os.path.join(root, f))
    return found


def build_icons():
    search_patterns = [
        "new_icon.*",
        "watermarked_img_*.*",
        os.path.join(os.path.expanduser("~"), "Downloads", "new_icon.*"),
        os.path.join(os.path.expanduser("~"), "Downloads", "watermarked_img_*.*"),
    ]
    matches = []
    for pattern in search_patterns:
        matches.extend(glob.glob(pattern))

    valid_exts = (".jpg", ".jpeg", ".png", ".webp")
    downloaded = [f for f in matches if f.lower().endswith(valid_exts)]

    if downloaded:
        source_path = max(downloaded, key=os.path.getmtime)
        print(f"📂 Using downloaded shield image: {source_path}")
        img = Image.open(source_path).convert("RGBA")
        w, h = img.size
        side = min(w, h)
        square_img = img.crop(((w - side) // 2, (h - side) // 2, (w + side) // 2, (h + side) // 2))
    elif os.path.exists("static/images/finale_logo.jpg"):
        print("📂 Extracting shield directly from static/images/finale_logo.jpg onto #0A192F...")
        img = Image.open("static/images/finale_logo.jpg").convert("RGBA")
        w, h = img.size
        # Crop upper shield area excluding bottom text
        shield_crop = img.crop((int(w * 0.25), int(h * 0.04), int(w * 0.75), int(h * 0.66)))
        pixels = shield_crop.load()
        cw, ch = shield_crop.size
        for y in range(ch):
            for x in range(cw):
                r, g, b, a = pixels[x, y]
                # Replace light neutral grey backdrop with #0A192F
                if max(r, g, b) - min(r, g, b) < 28 and r > 110:
                    pixels[x, y] = (10, 25, 47, 255)
        side = max(cw, ch) + 80
        square_img = Image.new("RGBA", (side, side), (10, 25, 47, 255))
        square_img.paste(shield_crop, ((side - cw) // 2, (side - ch) // 2))
    else:
        raise FileNotFoundError("Could not find downloaded icon or static/images/finale_logo.jpg")

    os.makedirs("static/images", exist_ok=True)
    square_img.resize((512, 512), Image.Resampling.LANCZOS).save("static/images/icon-512.png", "PNG")
    square_img.resize((192, 192), Image.Resampling.LANCZOS).save("static/images/icon-192.png", "PNG")
    print("✅ Generated static/images/icon-512.png and static/images/icon-192.png")


def update_manifest(manifest_paths):
    if not manifest_paths:
        manifest_paths = ["static/manifest.json"]
    for path in manifest_paths:
        data = {}
        if os.path.exists(path):
            with open(path, "r", encoding="utf-8-sig") as f:
                data = json.load(f)

        data["id"] = "https://inheritancebox.com/"
        data["name"] = "InheritanceBox | Digital Legacy ibox"
        data["short_name"] = "iBox"
        data["start_url"] = "/"
        data["scope"] = "/"
        data["display"] = "standalone"
        data["background_color"] = "#0A192F"
        data["theme_color"] = "#0A192F"
        data["prefer_related_applications"] = False
        data["related_applications"] = [
            {
                "platform": "webapp",
                "url": "https://inheritancebox.com/static/manifest.json",
                "id": "https://inheritancebox.com/",
            }
        ]
        data["icons"] = [
            {"src": "/static/images/icon-192.png", "sizes": "192x192", "type": "image/png", "purpose": "any"},
            {"src": "/static/images/icon-512.png", "sizes": "512x512", "type": "image/png", "purpose": "any"},
            {"src": "/static/images/icon-192.png", "sizes": "192x192", "type": "image/png", "purpose": "maskable"},
            {"src": "/static/images/icon-512.png", "sizes": "512x512", "type": "image/png", "purpose": "maskable"},
        ]
        with open(path, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2)
        print(f"✅ Updated {path} (short_name='iBox', canonical id locked)")


def update_base_html(base_paths):
    for path in base_paths:
        with open(path, "r", encoding="utf-8-sig") as f:
            content = f.read()

        # Strip any ?v= query strings from manifest.json references
        updated = re.sub(r"manifest\.json\?v=[^\"']+", "manifest.json", content)
        if updated != content:
            with open(path, "w", encoding="utf-8") as f:
                f.write(updated)
            print(f"✅ Cleaned manifest query strings in {path}")
        else:
            print(f"✅ Verified {path} already has clean manifest URL")


def update_sw_js(sw_paths):
    sw_code = """const CACHE_NAME = 'inheritancebox-v2026.14';
const ASSETS_TO_CACHE = [
  '/static/css/theme.css',
  '/static/js/app.js',
  '/static/manifest.json',
  '/static/images/icon-192.png',
  '/static/images/icon-512.png'
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
  if (!event.request.url.startsWith('http')) return;

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

  event.respondWith(
    caches.match(event.request, { ignoreSearch: true }).then((cachedResponse) => {
      if (cachedResponse) return cachedResponse;
      return fetch(event.request).catch(() => Response.error());
    })
  );
});
"""
    if not sw_paths:
        sw_paths = ["static/sw.js"]
    for path in sw_paths:
        with open(path, "w", encoding="utf-8") as f:
            f.write(sw_code)
        print(f"✅ Updated {path} to cache v2026.14 (network-first manifest)")


def git_push():
    print("🚀 Committing and pushing to trigger Coolify deploy...")
    subprocess.run(["git", "add", "."], check=True)
    commit = subprocess.run(
        ["git", "commit", "-m", "Deploy iBox adaptive icon and duplicate-proof PWA"],
        capture_output=True,
        text=True,
    )
    if commit.returncode == 0:
        print(commit.stdout.strip())
    else:
        print("ℹ️ Commit status:", commit.stdout.strip() or commit.stderr.strip())
    subprocess.run(["git", "push"], check=True)
    print("🎉 Done! Coolify is deploying your update now.")


if __name__ == "__main__":
    files = find_project_files(["manifest.json", "base.html", "sw.js"])
    build_icons()
    update_manifest(files["manifest.json"])
    update_base_html(files["base.html"])
    update_sw_js(files["sw.js"])
    git_push()