import os
import re
import subprocess

SKIP_DIRS = {".git", "venv", ".venv", "env", "node_modules", "__pycache__", "staticfiles"}


def find_file(filename):
    for root, dirs, files in os.walk("."):
        dirs[:] = [d for d in dirs if d not in SKIP_DIRS]
        if filename in files:
            return os.path.join(root, filename)
    return None


def patch_app_js():
    path = find_file("app.js") or "static/js/app.js"
    os.makedirs(os.path.dirname(path), exist_ok=True)

    app_js_code = """// Register Service Worker Silently (Never Force-Reload Active Tabs)
if ('serviceWorker' in navigator) {
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
    print(f"✅ Patched {path}: removed forced controllerchange page reload.")


def patch_sw_js():
    path = find_file("sw.js") or "static/sw.js"
    if not os.path.exists(path):
        print("⚠️ sw.js not found, skipping.")
        return

    with open(path, "r", encoding="utf-8-sig") as f:
        content = f.read()

    updated = re.sub(
        r"const CACHE_NAME = '[^']+';",
        "const CACHE_NAME = 'inheritancebox-v2026.16';",
        content,
        count=1,
    )
    with open(path, "w", encoding="utf-8") as f:
        f.write(updated)
    print(f"✅ Patched {path}: bumped cache to inheritancebox-v2026.16.")


def patch_base_html():
    path = find_file("base.html")
    if not path:
        print("⚠️ base.html not found, skipping.")
        return

    with open(path, "r", encoding="utf-8-sig") as f:
        content = f.read()

    # Prevent Cold-Start Hero Reset from bouncing internal same-site clicks back to '/'
    old_cold_start = "if (!isOngoingSession) {"
    new_cold_start = (
        "const isInternalNav = document.referrer && document.referrer.startsWith(window.location.origin);\n"
        "      if (!isOngoingSession && !isInternalNav) {"
    )
    if "isInternalNav" not in content and old_cold_start in content:
        content = content.replace(old_cold_start, new_cold_start, 1)

    # Keep 1.5s loader active on page load
    content = content.replace(
        '<div id="vault-page-loader" class="vault-loader-overlay" aria-hidden="true"',
        '<div id="vault-page-loader" class="vault-loader-overlay active" aria-hidden="false"',
        1,
    )
    content = re.sub(
        r"(function scheduleLoaderDismissal\(\)\s*\{\s*)(?:hideNavLoader\(\);|setTimeout\(hideNavLoader,\s*\d+\);)",
        r"\1setTimeout(hideNavLoader, 1500);",
        content,
        count=1,
    )

    with open(path, "w", encoding="utf-8") as f:
        f.write(content)
    print(f"✅ Patched {path}: protected same-site clicks & kept 1.5s loader.")


def git_push():
    print("🚀 Committing and pushing single-click navigation fix...")
    subprocess.run(["git", "add", "."], check=True)
    commit = subprocess.run(
        ["git", "commit", "-m", "Fix first-click reload hijack and preserve 1.5s loader"],
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
    patch_app_js()
    patch_sw_js()
    patch_base_html()
    git_push()