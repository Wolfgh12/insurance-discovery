from .base import *

DEBUG = True

ALLOWED_HOSTS = ['127.0.0.1', 'localhost', '*']

DATABASES = {
    'default': {
        'ENGINE': 'django.db.backends.postgresql',
        'NAME': 'legacytrace_db',
        'USER': 'postgres',
        'PASSWORD': 'Nana1234',
        'HOST': '127.0.0.1',
        'PORT': '5433',
    }
}

# Paystack Sandbox / Test API Credentials
PAYSTACK_PUBLIC_KEY = 'pk_test_f74c99ee13063ecc39fd9af4be16f23de21a11b3'
PAYSTACK_SECRET_KEY = 'sk_test_c40d6c80263fef031ca0079a7ad21a22d65f729b'

# Email Service Configuration (Live Gmail SMTP)
EMAIL_BACKEND = 'django.core.mail.backends.smtp.EmailBackend'
EMAIL_HOST = 'smtp.gmail.com'
EMAIL_PORT = 587
EMAIL_USE_TLS = True
EMAIL_HOST_USER = 'legacytrace442@gmail.com'
EMAIL_HOST_PASSWORD = 'yypobavqkayphgdj'
DEFAULT_FROM_EMAIL = 'LegacyTrace <legacytrace442@gmail.com>'
SERVER_EMAIL = 'legacytrace442@gmail.com'