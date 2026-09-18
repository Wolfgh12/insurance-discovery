import os
from pathlib import Path

# BASE_DIR points to project root (3 levels up: base.py -> settings -> core -> root)
BASE_DIR = Path(__file__).resolve().parent.parent.parent

# Decoupled Secret Key: pulls from environment with a secure fallback
SECRET_KEY = os.environ.get(
    'DJANGO_SECRET_KEY', 
    'django-insecure-change-this-in-production-vault'
)

# Application definition
INSTALLED_APPS = [
    'django.contrib.admin',
    'django.contrib.auth',
    'django.contrib.contenttypes',
    'django.contrib.sessions',
    'django.contrib.messages',
    'django.contrib.staticfiles',

    # Third-party packages
    'rest_framework',
    'corsheaders',

    # Local application
    'vault',
]

MIDDLEWARE = [
    'corsheaders.middleware.CorsMiddleware',
    'django.middleware.security.SecurityMiddleware',
    'django.contrib.sessions.middleware.SessionMiddleware',
    'django.middleware.common.CommonMiddleware',
    'django.middleware.csrf.CsrfViewMiddleware',
    'django.contrib.auth.middleware.AuthenticationMiddleware',
    'django.contrib.messages.middleware.MessageMiddleware',
    'django.middleware.clickjacking.XFrameOptionsMiddleware',
]

ROOT_URLCONF = 'core.urls'

TEMPLATES = [
    {
        'BACKEND': 'django.template.backends.django.DjangoTemplates',
        'DIRS': [BASE_DIR / 'templates'],
        'APP_DIRS': True,
        'OPTIONS': {
            'context_processors': [
                'django.template.context_processors.debug',
                'django.template.context_processors.request',
                'django.contrib.auth.context_processors.auth',
                'django.contrib.messages.context_processors.messages',
                'vault.context_processors.platform_settings', 
            ],
        },
    },
]

WSGI_APPLICATION = 'core.wsgi.application'

# Hardened Password Policies (Zero-Trust Minimum Length)
AUTH_PASSWORD_VALIDATORS = [
    {'NAME': 'django.contrib.auth.password_validation.UserAttributeSimilarityValidator'},
    {
        'NAME': 'django.contrib.auth.password_validation.MinimumLengthValidator',
        'OPTIONS': {'min_length': 10},
    },
    {'NAME': 'django.contrib.auth.password_validation.CommonPasswordValidator'},
    {'NAME': 'django.contrib.auth.password_validation.NumericPasswordValidator'},
]

# Dedicated Cache Backend (Powers Login & Biometric Brute-Force Rate Limiting)
CACHES = {
    'default': {
        'BACKEND': 'django.core.cache.backends.locmem.LocMemCache',
        'LOCATION': 'legacytrace-security-cache',
        'TIMEOUT': 900,
        'OPTIONS': {
            'MAX_ENTRIES': 2000,
        }
    }
}

# ==============================================================================
# BROWSER & TRANSPORT SECURITY BOUNDARIES
# ==============================================================================

# Session & Authentication Cookie Protection
SESSION_COOKIE_HTTPONLY = True          # Blocks JavaScript/XSS from accessing session IDs
SESSION_COOKIE_SAMESITE = 'Lax'         # Mitigates cross-site request forgery across tabs
SESSION_COOKIE_AGE = 86400 * 7          # 7-day maximum session duration
SESSION_EXPIRE_AT_BROWSER_CLOSE = False
SESSION_SAVE_EVERY_REQUEST = True

# CSRF Cookie Protection
CSRF_COOKIE_HTTPONLY = False            # Set to False so client AJAX scripts can fetch tokens
CSRF_COOKIE_SAMESITE = 'Lax'
CSRF_COOKIE_AGE = 86400 * 7

# Clickjacking & Content Spoofing Defenses
X_FRAME_OPTIONS = 'DENY'                # Forbids embedding in iframes (anti-clickjacking)
SECURE_CONTENT_TYPE_NOSNIFF = True      # Prevents browser MIME-type confusion / drive-by exploits
SECURE_CROSS_ORIGIN_OPENER_POLICY = 'same-origin'
SECURE_REFERRER_POLICY = 'strict-origin-when-cross-origin'

# Restrict CORS to trusted local/gateway domains by default
CORS_ALLOW_ALL_ORIGINS = False
CORS_ALLOW_CREDENTIALS = True

# Internationalization & Regional Telemetry
LANGUAGE_CODE = 'en-us'
TIME_ZONE = 'UTC'
USE_I18N = True
USE_TZ = True

# Asset & Depository Routing
STATIC_URL = '/static/'
STATICFILES_DIRS = [BASE_DIR / 'static']
STATIC_ROOT = BASE_DIR / 'staticfiles'

MEDIA_URL = '/media/'
MEDIA_ROOT = BASE_DIR / 'media'

DEFAULT_AUTO_FIELD = 'django.db.models.BigAutoField'
AUTH_USER_MODEL = 'vault.CustomUser'

# Authentication Redirection Routes
LOGIN_URL = '/accounts/login/'
LOGIN_REDIRECT_URL = '/dashboard/'
LOGOUT_REDIRECT_URL = '/'

# Paystack Gateway Settings
PAYSTACK_PUBLIC_KEY = os.environ.get('PAYSTACK_PUBLIC_KEY', '')
PAYSTACK_SECRET_KEY = os.environ.get('PAYSTACK_SECRET_KEY', '')