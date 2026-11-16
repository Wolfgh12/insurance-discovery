import json
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


def setup_canonical_domain():
    os.makedirs("vault", exist_ok=True)
    mw_path = os.path.join("vault", "canonical_middleware.py")
    mw_code = """from django.http import HttpResponsePermanentRedirect


class CanonicalDomainMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        host = request.get_host().split(':')[0].lower()
        if host == 'www.inheritancebox.com':
            return HttpResponsePermanentRedirect(
                f"https://inheritancebox.com{request.get_full_path()}"
            )
        return self.get_response(request)
"""
    with open(mw_path, "w", encoding="utf-8") as f:
        f.write(mw_code)
    print(f"✅ Created {mw_path}")

    prod_path = find_file("production.py")
    if prod_path:
        with open(prod_path, "r", encoding="utf-8-sig") as f:
            content = f.read()

        mw_entry = "'vault.canonical_middleware.CanonicalDomainMiddleware'"
        if mw_entry not in content and "MIDDLEWARE = list(MIDDLEWARE)" in content:
            content = content.replace(
                "MIDDLEWARE = list(MIDDLEWARE)",
                "MIDDLEWARE = list(MIDDLEWARE)\n"
                f"if {mw_entry} not in MIDDLEWARE:\n"
                f"    MIDDLEWARE.insert(0, {mw_entry})",
                1,
            )
            with open(prod_path, "w", encoding="utf-8") as f:
                f.write(content)
            print(f"✅ Updated {prod_path}: enforced 301 redirect from www to inheritancebox.com")


def update_manifest():
    path = find_file("manifest.json") or "static/manifest.json"
    with open(path, "r", encoding="utf-8-sig") as f:
        data = json.load(f)

    data["id"] = "https://inheritancebox.com/"
    data["short_name"] = "iBox"
    data["prefer_related_applications"] = False
    data["related_applications"] = [
        {
            "platform": "webapp",
            "url": "https://inheritancebox.com/static/manifest.json",
            "id": "https://inheritancebox.com/",
        },
        {
            "platform": "webapp",
            "url": "https://inheritancebox.com/static/manifest.json",
            "id": "/",
        },
    ]
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)
    print(f"✅ Updated {path}: dual-ID detection enabled for iBox")


def update_base_html():
    path = find_file("base.html")
    if not path:
        raise FileNotFoundError("base.html not found")

    with open(path, "r", encoding="utf-8-sig") as f:
        content = f.read()

    # 1. Fail-closed CSS so buttons never flash before device check completes
    old_css_pattern = re.compile(
        r"/\* Auto-hide all installation buttons & banners when running inside installed app \*/.*?"
        r"\.app-is-installed \.pwa-install-element\s*\{\s*display:\s*none\s*!important;\s*\}",
        re.DOTALL,
    )
    new_css = """/* Fail-closed: hide PWA buttons until device install state is verified */
    html:not(.pwa-ready) .pwa-install-element,
    .app-is-standalone .pwa-install-element {
      display: none !important;
    }
    @media (display-mode: standalone) {
      .pwa-install-element {
        display: none !important;
      }
    }"""
    content = old_css_pattern.sub(new_css, content, count=1)

    # 2. Replace PWA pipeline with 3-state detector + "Already Installed • Open iBox" modal
    new_pipeline = """<!-- Already Installed Confirmation & Launch Modal -->
  <div id="pwa-already-installed-modal" style="display: none; position: fixed; inset: 0; z-index: 99999999; background: rgba(10, 25, 47, 0.88); backdrop-filter: blur(14px); -webkit-backdrop-filter: blur(14px); align-items: center; justify-content: center; padding: 1.25rem;">
    <div style="background: #0B192C; border: 2px solid #10B981; border-radius: 24px; padding: 2.25rem 1.75rem; max-width: 440px; width: 100%; color: #ffffff; text-align: center; box-shadow: 0 25px 60px rgba(0, 0, 0, 0.7), 0 0 35px rgba(16, 185, 129, 0.3);">
      <div style="width: 64px; height: 64px; margin: 0 auto 1.1rem; border-radius: 18px; overflow: hidden; border: 2px solid #10B981; box-shadow: 0 8px 24px rgba(16, 185, 129, 0.35);">
        <img src="{% static 'images/icon-192.png' %}" alt="iBox App Icon" style="width: 100%; height: 100%; object-fit: cover; display: block;">
      </div>
      <div style="background: rgba(16, 185, 129, 0.18); color: #34D399; border: 1px solid #10B981; font-size: 0.72rem; font-weight: 900; padding: 4px 12px; border-radius: 6px; display: inline-block; text-transform: uppercase; letter-spacing: 0.6px; margin-bottom: 0.65rem;">
        ✅ Installed on This Device
      </div>
      <h3 style="margin: 0 0 0.5rem; font-size: 1.3rem; font-weight: 900; letter-spacing: -0.3px;">
        iBox Is Already Installed
      </h3>
      <p id="pwa-already-installed-msg" style="margin: 0 0 1.4rem; font-size: 0.86rem; color: #CBD5E1; line-height: 1.6;">
        InheritanceBox (<strong>iBox</strong>) is already installed on your device—no duplicate download is needed. Tap below to open your installed app.
      </p>
      <div style="display: flex; flex-direction: column; gap: 10px;">
        <a
          id="btn-launch-installed-ibox"
          href="https://inheritancebox.com/"
          target="_blank"
          rel="noopener"
          onclick="closeAlreadyInstalledModal()"
          style="width: 100%; background: linear-gradient(135deg, #059669 0%, #10B981 100%); color: #ffffff; text-decoration: none; padding: 0.9rem; border-radius: 12px; font-size: 0.94rem; font-weight: 900; display: inline-flex; align-items: center; justify-content: center; gap: 8px; box-shadow: 0 4px 18px rgba(16, 185, 129, 0.45);"
        >
          Open iBox App ➔
        </a>
        <button
          type="button"
          onclick="closeAlreadyInstalledModal()"
          style="width: 100%; background: transparent; border: 1px solid rgba(255, 255, 255, 0.15); color: #94A3B8; padding: 0.75rem; border-radius: 12px; font-size: 0.82rem; font-weight: 700; cursor: pointer; font-family: inherit;"
        >
          Stay in Browser ✕
        </button>
      </div>
    </div>
  </div>

  <!-- PWA 3-State Installation & Already-Installed Controller -->
  <script>
    (function () {
      let deferredInstallPrompt = null;
      const INSTALL_STORAGE_KEY = 'ibox_pwa_installed_v2';
      const isStandalone = window.matchMedia('(display-mode: standalone)').matches || window.navigator.standalone === true;
      const isIOS = /iPad|iPhone|iPod/.test(navigator.userAgent) && !window.MSStream;

      function setInstallFlag() {
        const domainAttr = window.location.hostname.endsWith('inheritancebox.com') ? '; domain=.inheritancebox.com' : '';
        document.cookie = `${INSTALL_STORAGE_KEY}=true; path=/; max-age=31536000; SameSite=Lax${domainAttr}`;
        try { localStorage.setItem(INSTALL_STORAGE_KEY, 'true'); } catch (e) {}
      }

      function clearInstallFlag() {
        const domainAttr = window.location.hostname.endsWith('inheritancebox.com') ? '; domain=.inheritancebox.com' : '';
        document.cookie = `${INSTALL_STORAGE_KEY}=; path=/; max-age=0; SameSite=Lax${domainAttr}`;
        try { localStorage.removeItem(INSTALL_STORAGE_KEY); } catch (e) {}
      }

      function hasSavedInstallFlag() {
        try {
          if (localStorage.getItem(INSTALL_STORAGE_KEY) === 'true') return true;
        } catch (e) {}
        return document.cookie.split(';').some(function (c) {
          return c.trim().startsWith(INSTALL_STORAGE_KEY + '=true');
        });
      }

      function hideAllInstallButtons() {
        document.documentElement.classList.remove('pwa-ready');
        document.documentElement.classList.add('app-is-standalone');
        if (document.body) document.body.classList.add('app-is-standalone');
      }

      function renderDownloadState() {
        document.documentElement.classList.remove('app-is-standalone', 'pwa-already-installed');
        document.documentElement.classList.add('pwa-ready');
      }

      function renderAlreadyInstalledState() {
        document.documentElement.classList.remove('app-is-standalone');
        document.documentElement.classList.add('pwa-ready', 'pwa-already-installed');
        const labelText = isIOS ? '✅ Installed on Home Screen' : '✅ Already Installed • Open iBox';

        document.querySelectorAll('.pwa-install-element').forEach(function (el) {
          const actionTarget = (el.tagName === 'BUTTON' || el.tagName === 'A')
            ? el
            : el.querySelector('button, a');
          if (actionTarget) {
            actionTarget.textContent = labelText;
            actionTarget.style.borderColor = '#10B981';
            actionTarget.style.color = '#34D399';
          }
          const bannerTitle = el.querySelector('.pwa-chip-title');
          if (bannerTitle) {
            bannerTitle.textContent = 'iBox Is Installed on Your Device';
          }
        });
      }

      async function syncInstallationState() {
        // State 1: Currently inside the opened standalone iBox app
        if (isStandalone) {
          setInstallFlag();
          hideAllInstallButtons();
          return 'standalone';
        }

        // State 2: Check device-level installed apps via Chromium API
        if ('getInstalledRelatedApps' in navigator) {
          try {
            const relatedApps = await navigator.getInstalledRelatedApps();
            if (relatedApps && relatedApps.length > 0) {
              setInstallFlag();
              renderAlreadyInstalledState();
              return 'installed';
            }
          } catch (e) {}
        }

        // State 3: Check cross-path cookie / storage if browser hasn't offered a fresh install prompt
        if (hasSavedInstallFlag() && !deferredInstallPrompt) {
          renderAlreadyInstalledState();
          return 'installed';
        }

        // State 4: Not installed -> show Download App if browser supports install (or iOS Safari)
        if (deferredInstallPrompt || isIOS) {
          renderDownloadState();
          return 'installable';
        }

        hideAllInstallButtons();
        return 'unsupported';
      }

      syncInstallationState();

      // Browser fires this ONLY when iBox is NOT installed (or was uninstalled by user)
      window.addEventListener('beforeinstallprompt', function (e) {
        e.preventDefault();
        deferredInstallPrompt = e;
        clearInstallFlag();
        if (!isStandalone) {
          renderDownloadState();
        }
      });

      window.openAlreadyInstalledModal = function () {
        const modal = document.getElementById('pwa-already-installed-modal');
        const msg = document.getElementById('pwa-already-installed-msg');
        const launchBtn = document.getElementById('btn-launch-installed-ibox');
        if (isIOS) {
          if (msg) {
            msg.innerHTML = 'InheritanceBox (<strong>iBox</strong>) is already added to your iPhone Home Screen. Tap the <strong>iBox</strong> shield icon on your Home Screen to open it.';
          }
          if (launchBtn) launchBtn.style.display = 'none';
        }
        if (modal) modal.style.display = 'flex';
      };

      window.closeAlreadyInstalledModal = function () {
        const modal = document.getElementById('pwa-already-installed-modal');
        if (modal) modal.style.display = 'none';
      };

      const installVoiceAudio = new Audio("{% static 'audio/install_prompt.mp3' %}?v=1");
      installVoiceAudio.preload = "auto";

      function playPwaInstallVoicePrompt() {
        try {
          installVoiceAudio.currentTime = 0;
          installVoiceAudio.play().catch(function () {});
        } catch (e) {}
      }

      async function runPrePackagingAnimation() {
        const progressBar = document.getElementById('pwa-progress-bar');
        const percentText = document.getElementById('pwa-download-percent');
        const statusText = document.getElementById('pwa-download-status');
        const fileText = document.getElementById('pwa-download-file');
        const installBtn = document.getElementById('btn-execute-pwa-install');

        const packageItems = [
          { label: "App Manifest", url: "{% static 'manifest.json' %}" },
          { label: "Core Stylesheet", url: "{% static 'css/theme.css' %}" },
          { label: "Security Emblems", url: "{% static 'images/finale_logo.jpg' %}?v=9" },
          { label: "Offline Shell", url: "{% static 'images/hacker.png' %}" }
        ];

        try {
          if ('caches' in window) {
            caches.open('inheritancebox-runtime-v1').then(function (cache) {
              packageItems.forEach(function (item) {
                fetch(item.url, { cache: 'force-cache' }).then(function (res) {
                  if (res && res.ok) cache.put(item.url, res);
                }).catch(function () {});
              });
            }).catch(function () {});
          }
        } catch (err) {}

        if (progressBar) progressBar.style.width = '0%';
        if (percentText) percentText.textContent = '0%';
        if (statusText) statusText.textContent = 'CAPTURING PACKAGES...';
        if (installBtn) {
          installBtn.disabled = true;
          installBtn.style.opacity = '0.7';
          installBtn.style.cursor = 'not-allowed';
          installBtn.style.background = 'rgba(255, 255, 255, 0.1)';
          installBtn.innerHTML = 'Packaging Offline ibox... ⏳';
        }

        for (let i = 0; i < packageItems.length; i++) {
          const percent = Math.round(((i + 1) / packageItems.length) * 100);
          if (progressBar) progressBar.style.width = percent + '%';
          if (percentText) percentText.textContent = percent + '%';
          if (fileText) fileText.textContent = 'Prepared: ' + packageItems[i].label;
          await new Promise(function (resolve) { setTimeout(resolve, 220); });
        }

        if (statusText) statusText.textContent = 'PACKAGES READY';
        if (fileText) fileText.textContent = 'Ready for device installation.';
        if (installBtn) {
          installBtn.disabled = false;
          installBtn.style.opacity = '1';
          installBtn.style.cursor = 'pointer';
          installBtn.style.background = 'linear-gradient(135deg, #059669 0%, #10B981 100%)';
          installBtn.style.boxShadow = '0 4px 18px rgba(16, 185, 129, 0.45)';
          installBtn.innerHTML = 'Install InheritanceBox Now ➔';
        }
      }

      window.openPwaSuccessModal = function () {
        const modal = document.getElementById('pwa-install-success-modal');
        if (modal) {
          modal.style.display = 'flex';
          runPrePackagingAnimation();
          playPwaInstallVoicePrompt();
        }
      };

      window.closePwaSuccessModal = function () {
        const modal = document.getElementById('pwa-install-success-modal');
        if (modal) modal.style.display = 'none';
        try {
          if (installVoiceAudio) {
            installVoiceAudio.pause();
            installVoiceAudio.currentTime = 0;
          }
        } catch (e) {}
        if ('speechSynthesis' in window) {
          window.speechSynthesis.cancel();
        }
      };

      window.openIosInstallTooltip = function () {
        const tooltip = document.getElementById('ios-install-tooltip');
        if (tooltip) tooltip.style.display = 'block';
      };

      window.closeIosInstallTooltip = function () {
        const tooltip = document.getElementById('ios-install-tooltip');
        if (tooltip) tooltip.style.display = 'none';
      };

      window.triggerPwaInstall = async function () {
        const state = await syncInstallationState();
        if (state === 'installed' || state === 'standalone') {
          window.openAlreadyInstalledModal();
          return;
        }
        window.openPwaSuccessModal();
      };

      window.confirmAndExecuteInstall = function () {
        window.closePwaSuccessModal();

        if (deferredInstallPrompt) {
          deferredInstallPrompt.prompt();
          deferredInstallPrompt.userChoice.then(function (choiceResult) {
            if (choiceResult.outcome === 'accepted') {
              setInstallFlag();
              renderAlreadyInstalledState();
              deferredInstallPrompt = null;
            }
          }).catch(function () {
            deferredInstallPrompt = null;
          });
        } else if (isIOS) {
          setInstallFlag();
          renderAlreadyInstalledState();
          window.openIosInstallTooltip();
        } else {
          setInstallFlag();
          renderAlreadyInstalledState();
          window.openAlreadyInstalledModal();
        }
      };

      window.addEventListener('appinstalled', function () {
        setInstallFlag();
        renderAlreadyInstalledState();
        window.closeIosInstallTooltip();
        deferredInstallPrompt = null;
      });
    })();
  </script>

  """

    pipeline_pattern = re.compile(
        r"<!-- PWA Native Installation Pipeline.*?<script>.*?</script>\s*",
        re.DOTALL,
    )
    if not pipeline_pattern.search(content):
        raise RuntimeError("Could not locate PWA Native Installation Pipeline block in base.html")

    content = pipeline_pattern.sub(new_pipeline, content, count=1)

    with open(path, "w", encoding="utf-8") as f:
        f.write(content)
    print(f"✅ Updated {path}: 3-state PWA button ('Already Installed • Open iBox') active")


def bump_sw_js():
    path = find_file("sw.js") or "static/sw.js"
    if not os.path.exists(path):
        return
    with open(path, "r", encoding="utf-8-sig") as f:
        content = f.read()
    updated = re.sub(
        r"const CACHE_NAME = '[^']+';",
        "const CACHE_NAME = 'inheritancebox-v2026.17';",
        content,
        count=1,
    )
    with open(path, "w", encoding="utf-8") as f:
        f.write(updated)
    print(f"✅ Updated {path}: cache bumped to inheritancebox-v2026.17")


def git_push():
    print("🚀 Committing and pushing 3-state PWA lockdown...")
    subprocess.run(["git", "add", "."], check=True)
    commit = subprocess.run(
        ["git", "commit", "-m", "Enforce canonical domain and 3-state Already Installed Open iBox PWA flow"],
        capture_output=True,
        text=True,
    )
    if commit.returncode == 0:
        print(commit.stdout.strip())
    else:
        print("ℹ️ Commit status:", commit.stdout.strip() or commit.stderr.strip())
    subprocess.run(["git", "push"], check=True)
    print("🎉 Pushed! Coolify is deploying your update now.")


if __name__ == "__main__":
    setup_canonical_domain()
    update_manifest()
    update_base_html()
    bump_sw_js()
    git_push()