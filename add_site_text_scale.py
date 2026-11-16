import os
import re
import subprocess
import sys


def patch_models():
    path = os.path.join("vault", "models.py")
    with open(path, "r", encoding="utf-8-sig") as f:
        content = f.read()

    if "ui_text_scale" in content:
        print("✅ vault/models.py already has ui_text_scale.")
        return

    target = """    module_wills_enabled = models.BooleanField(
        default=False,
        verbose_name="Enable Digital Wills & Deeds Module",
        help_text="Unchecking locks this module as 'Coming Soon' across home and dashboard."
    )

    updated_at = models.DateTimeField(auto_now=True)"""

    replacement = """    module_wills_enabled = models.BooleanField(
        default=False,
        verbose_name="Enable Digital Wills & Deeds Module",
        help_text="Unchecking locks this module as 'Coming Soon' across home and dashboard."
    )

    TEXT_SCALE_CHOICES = (
        ('100%', 'Standard (100% - Original)'),
        ('104%', 'Subtle Boost (104%)'),
        ('106%', 'Comfortable (106% - Recommended)'),
        ('110%', 'Medium-Large (110%)'),
        ('114%', 'Large (114%)'),
    )
    ui_text_scale = models.CharField(
        max_length=10,
        choices=TEXT_SCALE_CHOICES,
        default='106%',
        verbose_name="Site-Wide Text Size",
        help_text="Adjusts typography scale across all public and dashboard pages."
    )

    updated_at = models.DateTimeField(auto_now=True)"""

    if target not in content:
        raise RuntimeError("Could not locate PlatformConfiguration anchor in vault/models.py")

    content = content.replace(target, replacement, 1)
    content = content.replace(
        "'module_wills_enabled': False,",
        "'module_wills_enabled': False,\n                'ui_text_scale': '106%',",
        1,
    )

    with open(path, "w", encoding="utf-8") as f:
        f.write(content)
    print("✅ Patched vault/models.py: added ui_text_scale (default 106%).")


def patch_admin():
    path = os.path.join("vault", "admin.py")
    with open(path, "r", encoding="utf-8-sig") as f:
        content = f.read()

    if "'ui_text_scale'" in content:
        print("✅ vault/admin.py already has ui_text_scale.")
        return

    # Case A: Simple registration -> upgrade to ModelAdmin with list_editable dropdown
    simple_reg = "admin.site.register(PlatformConfiguration)"
    if simple_reg in content:
        upgraded = """@admin.register(PlatformConfiguration)
class PlatformConfigurationAdmin(admin.ModelAdmin):
    list_display = ('__str__', 'ui_text_scale', 'unlock_fee', 'registration_fee', 'annual_subscription_fee', 'updated_at')
    list_editable = ('ui_text_scale',)
"""
        content = content.replace(simple_reg, upgraded, 1)
        with open(path, "w", encoding="utf-8") as f:
            f.write(content)
        print("✅ Patched vault/admin.py: registered PlatformConfigurationAdmin with live ui_text_scale dropdown.")
        return

    # Case B: Existing PlatformConfigurationAdmin class
    match = re.search(
        r"(@admin\.register\(PlatformConfiguration\)\s*class\s+\w+\([^)]+\):.*?)(?=\n@admin\.register|\nclass\s+|\Z)",
        content,
        re.DOTALL,
    )
    if not match:
        raise RuntimeError("Could not locate PlatformConfiguration registration in vault/admin.py")

    block = match.group(1)
    orig_block = block

    if "list_display" in block:
        block = re.sub(r"(list_display\s*=\s*[\(\[])", r"\1'ui_text_scale', ", block, count=1)
    else:
        block += "\n    list_display = ('__str__', 'ui_text_scale', 'updated_at')\n"

    if "list_editable" in block:
        block = re.sub(r"(list_editable\s*=\s*[\(\[])", r"\1'ui_text_scale', ", block, count=1)
    else:
        block += "\n    list_editable = ('ui_text_scale',)\n"

    if "fieldsets" in block:
        block = re.sub(r"(['\"]fields['\"]\s*:\s*[\(\[])", r"\1'ui_text_scale', ", block, count=1)

    content = content.replace(orig_block, block, 1)
    with open(path, "w", encoding="utf-8") as f:
        f.write(content)
    print("✅ Patched vault/admin.py: added ui_text_scale to PlatformConfigurationAdmin.")


def patch_base_html():
    path = os.path.join("templates", "base.html")
    with open(path, "r", encoding="utf-8-sig") as f:
        content = f.read()

    if "html { font-size:" in content or "font-size: {{ platform_config.ui_text_scale" in content:
        print("✅ templates/base.html already has global font-size rule.")
        return

    target = "  <style>\n    :root {"
    replacement = """  <style>
    html {
      font-size: {{ platform_config.ui_text_scale|default:'106%' }};
    }

    :root {"""

    if target not in content:
        target = "    :root {"
        replacement = "    html {\n      font-size: {{ platform_config.ui_text_scale|default:'106%' }};\n    }\n\n    :root {"

    content = content.replace(target, replacement, 1)
    with open(path, "w", encoding="utf-8") as f:
        f.write(content)
    print("✅ Patched templates/base.html: bound root html font-size to platform_config.ui_text_scale.")


def migrate_and_push():
    py_exe = r".\venv\Scripts\python.exe" if os.path.exists(r".\venv\Scripts\python.exe") else sys.executable
    print(f"🚀 Running makemigrations & migrate with {py_exe}...")
    subprocess.run([py_exe, "manage.py", "makemigrations", "vault"], check=True)
    subprocess.run([py_exe, "manage.py", "migrate"], check=True)

    print("🚀 Committing and pushing to Git...")
    subprocess.run(["git", "add", "."], check=True)
    subprocess.run(["git", "commit", "-m", "Add Django Admin global text scale selector (106% default)"], check=True)
    subprocess.run(["git", "push"], check=True)
    print("🎉 Done! Coolify is deploying your update now.")


if __name__ == "__main__":
    patch_models()
    patch_admin()
    patch_base_html()
    migrate_and_push()