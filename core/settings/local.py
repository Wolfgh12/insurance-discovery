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