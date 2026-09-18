import os
try:
    from .settings.base import *
except ImportError:
    from .base import *

# 1. Zero Debug Information Leakage
DEBUG = os.environ.get('DEBUG', 'False').lower() in ('true', '1')

# 2. Dynamic Host Domain Locking & CSRF Security
ALLOWED_HOSTS = [
    host.strip() 
    for host in os.environ.get('ALLOWED_HOSTS', '*').split(',') 
    if host.strip()
]

# Required for Django 4.0+ when processing form POST requests over HTTPS
CSRF_TRUSTED_ORIGINS = [
    origin.strip()
    for origin in os.environ.get(
        'CSRF_TRUSTED_ORIGINS', 
        'https://*.sslip.io,https://*.185.216.75.85.sslip.io,https://mysikavault.com,https://www.mysikavault.com'
    ).split(',')
    if origin.strip()
]

# 3. Database Engine
DATABASES = {
    'default': {
        'ENGINE': 'django.db.backends.sqlite3',
        'NAME': BASE_DIR / 'db.sqlite3',
    }
}

# 4. Reverse Proxy & HTTPS Redirection
# Required for Coolify / Traefik reverse proxies terminating SSL
SECURE_PROXY_SSL_HEADER = ('HTTP_X_FORWARDED_PROTO', 'https')
SECURE_SSL_REDIRECT = os.environ.get('SECURE_SSL_REDIRECT', 'True').lower() in ('true', '1')

# 5. HTTP Strict Transport Security (HSTS - Anti-Downgrade / SSL-Stripping)
SECURE_HSTS_SECONDS = 31536000  # Enforce HTTPS strictly for 1 full year
SECURE_HSTS_INCLUDE_SUBDOMAINS = True
SECURE_HSTS_PRELOAD = True

# 6. Browser Boundary & Anti-Exploit Security Headers
SECURE_BROWSER_XSS_FILTER = True
SECURE_CONTENT_TYPE_NOSNIFF = True
SECURE_CROSS_ORIGIN_OPENER_POLICY = 'same-origin'
SECURE_REFERRER_POLICY = 'strict-origin-when-cross-origin'
X_FRAME_OPTIONS = 'DENY'

# 7. Cryptographic Cookie Protection (Anti-XSS & Anti-Hijacking)
SESSION_COOKIE_SECURE = True
SESSION_COOKIE_HTTPONLY = True          # Forbids JavaScript reading active user session ID
SESSION_COOKIE_SAMESITE = 'Lax'
CSRF_COOKIE_SECURE = True
CSRF_COOKIE_HTTPONLY = False           # Kept False to permit statutory CSRF retrieval by frontend AJAX forms
CSRF_COOKIE_SAMESITE = 'Lax'

# 8. Strict Inactivity & Vault Session Lifecycle
SESSION_COOKIE_AGE = 600                # 10 minutes of complete inactivity
SESSION_SAVE_EVERY_REQUEST = True       # Active legitimate user interaction resets the clock
SESSION_EXPIRE_AT_BROWSER_CLOSE = True

# 9. Paystack Payment Gateway API Credentials (Sanitized)
PAYSTACK_PUBLIC_KEY = os.environ.get('PAYSTACK_PUBLIC_KEY', '')
PAYSTACK_SECRET_KEY = os.environ.get('PAYSTACK_SECRET_KEY', '')

# 10. SMTP Production Mail Routing (Sanitized)
EMAIL_BACKEND = 'django.core.mail.backends.smtp.EmailBackend'
EMAIL_HOST = 'smtp.gmail.com'
EMAIL_PORT = int(os.environ.get('EMAIL_PORT', 587))
EMAIL_USE_TLS = True
EMAIL_HOST_USER = os.environ.get('EMAIL_HOST_USER', '')
EMAIL_HOST_PASSWORD = os.environ.get('EMAIL_HOST_PASSWORD', '')
DEFAULT_FROM_EMAIL = f"LegacyTrace <{EMAIL_HOST_USER}>" if EMAIL_HOST_USER else "LegacyTrace"
SERVER_EMAIL = EMAIL_HOST_USER