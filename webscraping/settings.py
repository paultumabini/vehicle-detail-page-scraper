"""
Django settings for the webscraping project.

Documentation:
https://docs.djangoproject.com/en/stable/topics/settings/
https://docs.djangoproject.com/en/stable/ref/settings/
"""

from __future__ import annotations

import os
from pathlib import Path

from django.core.exceptions import ImproperlyConfigured

# -----------------------------------------------------------------------------
# Paths
# -----------------------------------------------------------------------------

BASE_DIR = Path(__file__).resolve().parent.parent


def _env_bool(key: str, default: bool = False) -> bool:
    val = os.environ.get(key)
    if val is None:
        return default
    return val.lower() in ('1', 'true', 'yes', 'on')


def _env_list(key: str, default: str | None = None) -> list[str]:
    raw = os.environ.get(key, default or '')
    return [item.strip() for item in raw.split(',') if item.strip()]


# -----------------------------------------------------------------------------
# Core
# -----------------------------------------------------------------------------

# Default True so ``runserver`` works without env vars. In production set
# ``DJANGO_DEBUG=0`` (and ``DJANGO_SECRET_KEY`` — see below).
DEBUG = _env_bool('DJANGO_DEBUG', default=True)

# Set DJANGO_SECRET_KEY in production; never commit real secrets.
_LEGACY_INSECURE_KEY = (
    'django-insecure-&t^s6g^jbn^j5g=e6fp5es4hb=ofcyg7^s)575%6(s6*d#s8w#'
)
SECRET_KEY = os.environ.get('DJANGO_SECRET_KEY') or _LEGACY_INSECURE_KEY
if not DEBUG and SECRET_KEY == _LEGACY_INSECURE_KEY:
    raise ImproperlyConfigured(
        'Set DJANGO_SECRET_KEY in the environment when DEBUG is False.'
    )

if os.environ.get('DJANGO_ALLOWED_HOSTS'):
    ALLOWED_HOSTS = _env_list('DJANGO_ALLOWED_HOSTS')
else:
    # Set DJANGO_ALLOWED_HOSTS in production (comma-separated), e.g.
    # "example.com,www.example.com"
    ALLOWED_HOSTS = ['*']


# -----------------------------------------------------------------------------
# Applications
# -----------------------------------------------------------------------------

INSTALLED_APPS = [
    'project.apps.ProjectConfig',
    'users',
    'project.api',
    'jazzmin',
    'crispy_forms',
    'crispy_bootstrap4',
    'django.contrib.admin',
    'django.contrib.auth',
    'django.contrib.contenttypes',
    'django.contrib.sessions',
    'django.contrib.messages',
    'django.contrib.staticfiles',
    'storages',
    'rest_framework',
    'rest_framework.authtoken',
    'corsheaders',
]

# CorsMiddleware should run early (after SecurityMiddleware).
MIDDLEWARE = [
    'django.middleware.security.SecurityMiddleware',
    'corsheaders.middleware.CorsMiddleware',
    'django.contrib.sessions.middleware.SessionMiddleware',
    'django.middleware.common.CommonMiddleware',
    'django.middleware.csrf.CsrfViewMiddleware',
    'django.contrib.auth.middleware.AuthenticationMiddleware',
    'django.contrib.messages.middleware.MessageMiddleware',
    'django.middleware.clickjacking.XFrameOptionsMiddleware',
]

ROOT_URLCONF = 'webscraping.urls'

TEMPLATES = [
    {
        'BACKEND': 'django.template.backends.django.DjangoTemplates',
        'DIRS': [],
        'APP_DIRS': True,
        'OPTIONS': {
            'context_processors': [
                'django.template.context_processors.debug',
                'django.template.context_processors.request',
                'django.contrib.auth.context_processors.auth',
                'django.contrib.messages.context_processors.messages',
            ],
        },
    },
]

WSGI_APPLICATION = 'webscraping.wsgi.application'


# -----------------------------------------------------------------------------
# Database
# -----------------------------------------------------------------------------

DATABASES = {
    'default': {
        'ENGINE': 'django.db.backends.postgresql',
        'NAME': os.environ.get('POSTGRES_DB', os.environ.get('DB_NAME', 'webscraping')),
        'USER': os.environ.get('POSTGRES_USER', os.environ.get('DB_USER', 'admin')),
        'PASSWORD': os.environ.get(
            'POSTGRES_PASSWORD', os.environ.get('DB_PASSWORD', 'admin')
        ),
        'HOST': os.environ.get('POSTGRES_HOST', os.environ.get('DB_HOST', '127.0.0.1')),
        'PORT': os.environ.get('POSTGRES_PORT', os.environ.get('DB_PORT', '5432')),
    }
}


# -----------------------------------------------------------------------------
# Auth / passwords
# -----------------------------------------------------------------------------

AUTH_PASSWORD_VALIDATORS = [
    {
        'NAME': (
            'django.contrib.auth.password_validation.'
            'UserAttributeSimilarityValidator'
        ),
    },
    {
        'NAME': (
            'django.contrib.auth.password_validation.MinimumLengthValidator'
        ),
    },
    {
        'NAME': (
            'django.contrib.auth.password_validation.CommonPasswordValidator'
        ),
    },
    {
        'NAME': (
            'django.contrib.auth.password_validation.NumericPasswordValidator'
        ),
    },
]

LOGIN_REDIRECT_URL = 'home'
LOGIN_URL = 'login'

# Token lifetime for password reset links (seconds). Replaces deprecated
# PASSWORD_RESET_TIMEOUT_DAYS.
PASSWORD_RESET_TIMEOUT = int(
    os.environ.get('DJANGO_PASSWORD_RESET_TIMEOUT', str(60 * 60 * 24))
)


# -----------------------------------------------------------------------------
# Django REST Framework
# -----------------------------------------------------------------------------

REST_FRAMEWORK = {
    'DEFAULT_AUTHENTICATION_CLASSES': [
        'rest_framework.authentication.TokenAuthentication',
    ],
    'DEFAULT_PERMISSION_CLASSES': [
        'rest_framework.permissions.IsAuthenticated',
    ],
    'DEFAULT_RENDERER_CLASSES': [
        'rest_framework.renderers.JSONRenderer',
    ],
    'DEFAULT_PARSER_CLASSES': [
        'rest_framework.parsers.JSONParser',
    ],
    'DEFAULT_THROTTLE_CLASSES': [
        'rest_framework.throttling.AnonRateThrottle',
        'rest_framework.throttling.UserRateThrottle',
    ],
    'DEFAULT_THROTTLE_RATES': {
        'anon': os.environ.get('DRF_THROTTLE_ANON', '100/hr'),
        'user': os.environ.get('DRF_THROTTLE_USER', '100/hr'),
    },
}


# -----------------------------------------------------------------------------
# i18n / time
# -----------------------------------------------------------------------------

LANGUAGE_CODE = 'en-us'
TIME_ZONE = 'UTC'
USE_I18N = True
# True is recommended for new deployments; project historically used False to
# avoid naive-datetime warnings—migrate carefully if you flip this.
USE_TZ = False


# -----------------------------------------------------------------------------
# Static & media
# -----------------------------------------------------------------------------

STATIC_URL = 'static/'
STATICFILES_DIRS = [BASE_DIR / 'static']

MEDIA_URL = '/images/'
MEDIA_ROOT = BASE_DIR / 'static' / 'images'

DEFAULT_AUTO_FIELD = 'django.db.models.BigAutoField'

CRISPY_TEMPLATE_PACK = 'bootstrap4'


# -----------------------------------------------------------------------------
# Jazzmin (admin UI)
# -----------------------------------------------------------------------------


def jazzmin_user_avatar(user):
    """Sidebar avatar from users.Profile.image (related name: profile)."""
    from django.templatetags.static import static

    try:
        return user.profile.image.url
    except Exception:
        return static('vendor/adminlte/img/user2-160x160.jpg')


JAZZMIN_SETTINGS = {
    'site_logo': 'images/sb_sm.png',
    'show_ui_builder': False,
    'copyright': 'Scrape Bucket',
    'user_avatar': jazzmin_user_avatar,
    'changeform_format': 'horizontal_tabs',
    'custom_css': 'css/admin-extra.css',
    'custom_js': 'js/admin-extra.js',
}

JAZZMIN_UI_TWEAKS = {
    'theme': 'flatly',
    'hide_admin_paginator': True,
    'navbar': 'navbar-white navbar-light',
    'sidebar': 'sidebar-dark-primary',
    'accent': 'accent-primary',
    'actions_sticky_top': True,
    'footer_fixed': False,
}


# -----------------------------------------------------------------------------
# Email
# -----------------------------------------------------------------------------

EMAIL_BACKEND = 'django.core.mail.backends.smtp.EmailBackend'
EMAIL_HOST = os.environ.get('EMAIL_HOST', 'smtp.gmail.com')
EMAIL_PORT = int(os.environ.get('EMAIL_PORT', '587'))
EMAIL_USE_TLS = _env_bool('EMAIL_USE_TLS', default=True)
EMAIL_HOST_USER = os.environ.get('EMAIL_USER')
EMAIL_HOST_PASSWORD = os.environ.get('EMAIL_PASS')
DEFAULT_FROM_EMAIL = os.environ.get(
    'DEFAULT_FROM_EMAIL',
    EMAIL_HOST_USER or 'webmaster@localhost',
)


# -----------------------------------------------------------------------------
# django-storages / S3 (optional — enable when vars are set)
# -----------------------------------------------------------------------------

if (
    os.environ.get('AWS_STORAGE_BUCKET_NAME')
    and os.environ.get('AWS_ACCESS_KEY_ID')
    and os.environ.get('AWS_SECRET_ACCESS_KEY')
):
    AWS_ACCESS_KEY_ID = os.environ['AWS_ACCESS_KEY_ID']
    AWS_SECRET_ACCESS_KEY = os.environ['AWS_SECRET_ACCESS_KEY']
    AWS_STORAGE_BUCKET_NAME = os.environ['AWS_STORAGE_BUCKET_NAME']
    AWS_S3_FILE_OVERWRITE = False
    AWS_DEFAULT_ACL = None
    DEFAULT_FILE_STORAGE = 'storages.backends.s3boto3.S3Boto3Storage'


# -----------------------------------------------------------------------------
# CORS (django-cors-headers 4.x)
# -----------------------------------------------------------------------------

CORS_ALLOW_ALL_ORIGINS = _env_bool('CORS_ALLOW_ALL_ORIGINS', default=True)
CORS_ALLOW_CREDENTIALS = True
CORS_ALLOW_METHODS = [
    'DELETE',
    'GET',
    'OPTIONS',
    'PATCH',
    'POST',
    'PUT',
]
CORS_ALLOW_HEADERS = [
    'accept',
    'accept-encoding',
    'authorization',
    'content-type',
    'dnt',
    'origin',
    'user-agent',
    'x-csrftoken',
    'x-requested-with',
]

# When CORS_ALLOW_ALL_ORIGINS is False, set e.g.
# CORS_ALLOWED_ORIGINS=https://app.example.com,https://admin.example.com
if not CORS_ALLOW_ALL_ORIGINS:
    _cors_origins = _env_list('CORS_ALLOWED_ORIGINS')
    if _cors_origins:
        CORS_ALLOWED_ORIGINS = _cors_origins


# -----------------------------------------------------------------------------
# Sessions (optional hardening)
# -----------------------------------------------------------------------------

# SESSION_EXPIRE_AT_BROWSER_CLOSE = True
# SESSION_COOKIE_AGE = 600
# SESSION_SAVE_EVERY_REQUEST = True
