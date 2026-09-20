import os
from pathlib import Path
try:
    from .settings.base import *
except ImportError:
    from .base import *

# 1. Zero Debug Information Leakage
DEBUG = os.environ.get('DEBUG', 'False').lower() in ('true', '1')

# 2. Resilient Host Domain Locking & Reverse-Proxy Binding
env_hosts = os.environ.get('ALLOWED_HOSTS', '')

if env_hosts and env_hosts.strip() != '*':
    ALLOWED_HOSTS = [h.strip() for h in env_hosts.split(',') if h.strip()]
else:
    # Comprehensive default: covers apex domain, subdomains, Coolify sslip.io, IP, and local
    ALLOWED_HOSTS = [
        'mysikavault.com',
        'www.mysikavault.com',
        '.mysikavault.com',
        '.sslip.io',
        '185.216.75.85',
        'localhost',
        '127.0.0.1',
    ]

# Tell Django to trust the Host header sent by Coolify's Traefik reverse proxy
USE_X_FORWARDED_HOST = True

# Required for Django 4.0+ when processing form POST requests over HTTPS
CSRF_TRUSTED_ORIGINS = [ 
    origin.strip()
    for origin in os.environ.get(
        'CSRF_TRUSTED_ORIGINS', 
        'https://mysikavault.com,https://www.mysikavault.com,https://*.mysikavault.com,https://*.sslip.io'
    ).split(',')
    if origin.strip()
]

# 2B. Payload Clamping & Anti-OOM DoS Protection
DATA_UPLOAD_MAX_MEMORY_SIZE = 10 * 1024 * 1024  # 10 MB payload ceiling
FILE_UPLOAD_MAX_MEMORY_SIZE = 10 * 1024 * 1024  # 10 MB chunk in memory
DATA_UPLOAD_MAX_NUMBER_FIELDS = 1000            # Hash collision DoS mitigation

# 3. Middleware Configuration (Inject WhiteNoise for Static File Serving)
MIDDLEWARE = list(MIDDLEWARE)
if 'whitenoise.middleware.WhiteNoiseMiddleware' not in MIDDLEWARE:
    try:
        sec_index = MIDDLEWARE.index('django.middleware.security.SecurityMiddleware')
        MIDDLEWARE.insert(sec_index + 1, 'whitenoise.middleware.WhiteNoiseMiddleware')
    except ValueError:
        MIDDLEWARE.insert(0, 'whitenoise.middleware.WhiteNoiseMiddleware')

# 4. Static Files & WhiteNoise Storage
STATIC_URL = '/static/'
STATIC_ROOT = BASE_DIR / 'staticfiles'

static_source = BASE_DIR / 'static'
if static_source.exists():
    try:
        if static_source not in STATICFILES_DIRS:
            STATICFILES_DIRS = list(STATICFILES_DIRS) + [static_source]
    except NameError:
        STATICFILES_DIRS = [static_source]

STORAGES = {
    "default": {
        "BACKEND": "django.core.files.storage.FileSystemStorage",
    },
    "staticfiles": {
        "BACKEND": "whitenoise.storage.CompressedStaticFilesStorage",
    },
}
STATICFILES_STORAGE = 'whitenoise.storage.CompressedStaticFilesStorage'

# 5. Persistent Storage Resolution (Database & Media Files)
DEFAULT_DATA_DIR = Path('/app/data') if Path('/app').exists() else (BASE_DIR / 'data')
DATA_DIR = Path(os.environ.get('DATA_DIR', DEFAULT_DATA_DIR))

try:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
except (PermissionError, OSError):
    DATA_DIR = BASE_DIR / 'data'
    DATA_DIR.mkdir(parents=True, exist_ok=True)

MEDIA_URL = '/media/'
MEDIA_ROOT = DATA_DIR / 'media'
MEDIA_ROOT.mkdir(parents=True, exist_ok=True)

# 6. Hardened SQLite Database Engine
DATABASES = {
    'default': {
        'ENGINE': 'django.db.backends.sqlite3',
        'NAME': DATA_DIR / 'db.sqlite3',
        'OPTIONS': {
            'timeout': 60,  # 60-second mutex lock ceiling for concurrent Gunicorn workers
        },
    }
}

# 7. Reverse Proxy & HTTPS Redirection (Terminated by Traefik/Coolify)
SECURE_PROXY_SSL_HEADER = ('HTTP_X_FORWARDED_PROTO', 'https')
SECURE_SSL_REDIRECT = os.environ.get('SECURE_SSL_REDIRECT', 'True').lower() in ('true', '1')

# 8. HTTP Strict Transport Security (HSTS - Anti-Downgrade / SSL-Stripping)
SECURE_HSTS_SECONDS = 31536000  # 1 Full Year
SECURE_HSTS_INCLUDE_SUBDOMAINS = True
SECURE_HSTS_PRELOAD = True

# 9. Browser Boundary & Anti-Exploit Security Headers
SECURE_BROWSER_XSS_FILTER = True
SECURE_CONTENT_TYPE_NOSNIFF = True
SECURE_CROSS_ORIGIN_OPENER_POLICY = 'same-origin'
SECURE_REFERRER_POLICY = 'strict-origin-when-cross-origin'
X_FRAME_OPTIONS = 'DENY'

# 10. Cryptographic Cookie Protection (Anti-XSS & Anti-Hijacking)
SESSION_COOKIE_SECURE = True
SESSION_COOKIE_HTTPONLY = True          # JavaScript cannot access active user session
SESSION_COOKIE_SAMESITE = 'Lax'
CSRF_COOKIE_SECURE = True
CSRF_COOKIE_HTTPONLY = False           # Required for AJAX CSRF extraction
CSRF_COOKIE_SAMESITE = 'Lax'

# 11. Strict Inactivity & Vault Session Lifecycle
SESSION_COOKIE_AGE = 600                # 10 minutes of inactivity
SESSION_SAVE_EVERY_REQUEST = True       # Activity resets timeout clock
SESSION_EXPIRE_AT_BROWSER_CLOSE = True

# 12. Paystack Payment Gateway API Credentials
PAYSTACK_PUBLIC_KEY = os.environ.get('PAYSTACK_PUBLIC_KEY', '')
PAYSTACK_SECRET_KEY = os.environ.get('PAYSTACK_SECRET_KEY', '')

# 13. SMTP Production Mail Routing
EMAIL_BACKEND = 'django.core.mail.backends.smtp.EmailBackend'
EMAIL_HOST = 'smtp.gmail.com'
EMAIL_PORT = int(os.environ.get('EMAIL_PORT', 587))
EMAIL_USE_TLS = True
EMAIL_HOST_USER = os.environ.get('EMAIL_HOST_USER', '')
EMAIL_HOST_PASSWORD = os.environ.get('EMAIL_HOST_PASSWORD', '')
DEFAULT_FROM_EMAIL = f"mySikaVault <{EMAIL_HOST_USER}>" if EMAIL_HOST_USER else "mySikaVault"
SERVER_EMAIL = EMAIL_HOST_USER