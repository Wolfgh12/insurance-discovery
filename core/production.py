from .base import *
import os

DEBUG = False

# Replace 'yourusername' with your actual PythonAnywhere username
ALLOWED_HOSTS = [
    'yourusername.pythonanywhere.com',
    '127.0.0.1',
    'localhost',
]

DATABASES = {
    'default': {
        'ENGINE': 'django.db.backends.postgresql',
        'NAME': os.environ.get('DB_NAME', 'legacytrace_db'),
        'USER': os.environ.get('DB_USER', 'postgres'),
        'PASSWORD': os.environ.get('DB_PASSWORD', 'Nana1234'),
        'HOST': os.environ.get('DB_HOST', 'localhost'),
        'PORT': os.environ.get('DB_PORT', '5432'),
    }
}

# Production Security Headers
SECURE_BROWSER_XSS_FILTER = True
SECURE_CONTENT_TYPE_NOSNIFF = True
X_FRAME_OPTIONS = 'DENY'
CSRF_COOKIE_SECURE = True
SESSION_COOKIE_SECURE = True

# Paystack Payment Gateway API Credentials
PAYSTACK_PUBLIC_KEY = os.environ.get(
    'PAYSTACK_PUBLIC_KEY',
    'pk_test_f74c99ee13063ecc39fd9af4be16f23de21a11b3'
)
PAYSTACK_SECRET_KEY = os.environ.get(
    'PAYSTACK_SECRET_KEY',
    'sk_test_c40d6c80263fef031ca0079a7ad21a22d65f729b'
)

# SMTP Production Mail Routing
EMAIL_BACKEND = 'django.core.mail.backends.smtp.EmailBackend'
EMAIL_HOST = 'smtp.gmail.com'
EMAIL_PORT = 587
EMAIL_USE_TLS = True
EMAIL_HOST_USER = os.environ.get('EMAIL_HOST_USER', 'legacytrace442@gmail.com')
EMAIL_HOST_PASSWORD = os.environ.get('EMAIL_HOST_PASSWORD', 'yypobavqkayphgdj')
DEFAULT_FROM_EMAIL = f"LegacyTrace <{EMAIL_HOST_USER}>"
SERVER_EMAIL = EMAIL_HOST_USER