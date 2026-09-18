import os
from .base import *

DEBUG = True

ALLOWED_HOSTS = ['127.0.0.1', 'localhost', 'nanatest.pythonanywhere.com', '*']

# Auto-detect database: Use SQLite on PythonAnywhere/fallback, or Postgres if DB_PORT is explicitly set
if os.environ.get('USE_POSTGRES') == 'True':
    DATABASES = {
        'default': {
            'ENGINE': 'django.db.backends.postgresql',
            'NAME': os.environ.get('DB_NAME', 'legacytrace_db'),
            'USER': os.environ.get('DB_USER', 'postgres'),
            'PASSWORD': os.environ.get('DB_PASSWORD', 'Nana1234'),
            'HOST': os.environ.get('DB_HOST', '127.0.0.1'),
            'PORT': os.environ.get('DB_PORT', '5433'),
        }
    }
else:
    DATABASES = {
        'default': {
            'ENGINE': 'django.db.backends.sqlite3',
            'NAME': BASE_DIR / 'db.sqlite3',
        }
    }

# Paystack Sandbox / Test API Credentials
PAYSTACK_PUBLIC_KEY = os.environ.get('PAYSTACK_PUBLIC_KEY', 'pk_test_f74c99ee13063ecc39fd9af4be16f23de21a11b3')
PAYSTACK_SECRET_KEY = os.environ.get('PAYSTACK_SECRET_KEY', 'sk_test_c40d6c80263fef031ca0079a7ad21a22d65f729b')

# Email Service Configuration (Live Gmail SMTP)
EMAIL_BACKEND = 'django.core.mail.backends.smtp.EmailBackend'
EMAIL_HOST = 'smtp.gmail.com'
EMAIL_PORT = 587
EMAIL_USE_TLS = True
EMAIL_HOST_USER = os.environ.get('EMAIL_HOST_USER', 'legacytrace442@gmail.com')
EMAIL_HOST_PASSWORD = os.environ.get('EMAIL_HOST_PASSWORD', 'yypobavqkayphgdj')
DEFAULT_FROM_EMAIL = 'LegacyTrace <legacytrace442@gmail.com>'
SERVER_EMAIL = 'legacytrace442@gmail.com'