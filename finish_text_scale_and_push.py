import os
import subprocess
import sys


def patch_admin():
    path = os.path.join("vault", "admin.py")
    with open(path, "r", encoding="utf-8-sig") as f:
        content = f.read()

    if '"ui_text_scale"' in content or "'ui_text_scale'" in content:
        print("✅ vault/admin.py already has ui_text_scale configured.")
        return

    old_block = """    list_display = (
        "config_summary",
        "anti_inspect_badge",
        "dom_poison_badge",
        "required_questions_display",
        "unlock_fee_display",
        "annual_retainer_display",
        "active_modules_display",
        "updated_at",
    )
    list_display_links = ("config_summary",)
    fieldsets = (
        (
            "🛡️ Developer Security & Anti-Inspection Shield",
            {
                "fields": (
                    "security_anti_inspect_enabled",
                    "security_dom_poisoning_enabled",
                    "security_poison_density",
                ),
                "description": "Master Developer Controls: Toggle client-side inspection lockout, or engage hardcore DOM memory-poisoning.",
            },
        ),"""

    new_block = """    list_display = (
        "config_summary",
        "ui_text_scale",
        "anti_inspect_badge",
        "dom_poison_badge",
        "required_questions_display",
        "unlock_fee_display",
        "annual_retainer_display",
        "active_modules_display",
        "updated_at",
    )
    list_editable = ("ui_text_scale",)
    list_display_links = ("config_summary",)
    fieldsets = (
        (
            "🛡️ Developer Security & Anti-Inspection Shield",
            {
                "fields": (
                    "ui_text_scale",
                    "security_anti_inspect_enabled",
                    "security_dom_poisoning_enabled",
                    "security_poison_density",
                ),
                "description": "Master Developer Controls: Adjust global site text size, toggle client-side inspection lockout, or engage hardcore DOM memory-poisoning.",
            },
        ),"""

    if old_block not in content:
        raise RuntimeError("Could not locate PlatformConfigurationAdmin block in vault/admin.py")

    content = content.replace(old_block, new_block, 1)
    with open(path, "w", encoding="utf-8") as f:
        f.write(content)
    print("✅ Patched vault/admin.py: added live ui_text_scale dropdown to PlatformConfigurationAdmin.")


def migrate_and_push():
    py_exe = r".\venv\Scripts\python.exe" if os.path.exists(r".\venv\Scripts\python.exe") else sys.executable
    print(f"🚀 Running makemigrations & migrate with {py_exe}...")
    subprocess.run([py_exe, "manage.py", "makemigrations", "vault"], check=True)
    subprocess.run([py_exe, "manage.py", "migrate"], check=True)

    print("🚀 Committing and pushing to Git...")
    subprocess.run(["git", "add", "."], check=True)
    commit = subprocess.run(
        ["git", "commit", "-m", "Add Django Admin site-wide text size control (106% default)"],
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
    patch_admin()
    migrate_and_push()