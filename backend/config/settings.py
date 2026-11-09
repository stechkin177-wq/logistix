import os
from datetime import timedelta
from pathlib import Path

import dj_database_url
from django.core.exceptions import ImproperlyConfigured

from config.dbguard import check_database_url

BASE_DIR = Path(__file__).resolve().parent.parent


def env(name, default=None):
    return os.environ.get(name, default)


def env_bool(name, default=False):
    return str(os.environ.get(name, str(default))).lower() in ("1", "true", "yes", "on")


def env_list(name, default=""):
    return [v.strip() for v in os.environ.get(name, default).split(",") if v.strip()]


DEBUG = env_bool("DJANGO_DEBUG", False)
SECRET_KEY = env("DJANGO_SECRET_KEY")
if not SECRET_KEY:
    if not DEBUG:
        raise ImproperlyConfigured("DJANGO_SECRET_KEY must be set when DJANGO_DEBUG is false")
    SECRET_KEY = "dev-insecure-secret-key-change-me"
# В продакшене список хостов задаётся явно (без подстановочного по умолчанию); значения по
# умолчанию только для разработки. Пользовательские домены компаний (этап 5) надо добавлять сюда.
ALLOWED_HOSTS = env_list("DJANGO_ALLOWED_HOSTS", "localhost,127.0.0.1,testserver" if DEBUG else "")

INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "rest_framework",
    "corsheaders",
    "apps.core",
    "apps.billing",
    "apps.forwarding",
    "apps.finance",
    "apps.documents",
    "apps.drivers",
    "apps.fleet",
]

# Админка Django: в продакшене выключается DJANGO_ADMIN_ENABLED=false (или закрывается по IP
# на прокси); в разработке включена по умолчанию.
ADMIN_ENABLED = env_bool("DJANGO_ADMIN_ENABLED", True)

MIDDLEWARE = [
    "apps.core.middleware.TenantContextMiddleware",
    "corsheaders.middleware.CorsMiddleware",
    "django.middleware.security.SecurityMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]

ROOT_URLCONF = "config.urls"
WSGI_APPLICATION = "config.wsgi.application"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
            ],
        },
    },
]

# Serverless (демо на Vercel): соединения не переживают вызов функции, поэтому CONN_MAX_AGE=0,
# а URL базы проверяется на пулер (см. config/dbguard.py). В VPS/разработке не включается.
SERVERLESS = env_bool("DJANGO_SERVERLESS", False)

DATABASE_URL = env("DATABASE_URL", "postgres://logistix:logistix@127.0.0.1:5432/logistix")
# Вне serverless и без DEBUG пулер запрещён, пока не задано DATABASE_POOLER_OK=true.
check_database_url(
    DATABASE_URL,
    serverless=SERVERLESS,
    debug=DEBUG,
    pooler_ok=env_bool("DATABASE_POOLER_OK", False),
)
DATABASES = {
    "default": dj_database_url.parse(
        DATABASE_URL,
        conn_max_age=int(env("DATABASE_CONN_MAX_AGE") or (0 if SERVERLESS else 60)),
    )
}
DATABASES["default"]["ATOMIC_REQUESTS"] = True
# SSL: sslmode в URL либо DATABASE_SSL_REQUIRE=true. Переключатель ПРИНУЖДАЕТ: отсутствующий или
# слабый режим (disable/allow/prefer) становится require; require/verify-ca/verify-full не меняются.
if env_bool("DATABASE_SSL_REQUIRE", False):
    _db_options = DATABASES["default"].setdefault("OPTIONS", {})
    if _db_options.get("sslmode") not in ("require", "verify-ca", "verify-full"):
        _db_options["sslmode"] = "require"

AUTH_USER_MODEL = "core.User"
DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

AUTH_PASSWORD_VALIDATORS = [
    {"NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator"},
    {"NAME": "django.contrib.auth.password_validation.MinimumLengthValidator"},
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
    {"NAME": "django.contrib.auth.password_validation.NumericPasswordValidator"},
]

LANGUAGE_CODE = "ru"
TIME_ZONE = "Asia/Almaty"
USE_I18N = True
USE_TZ = True

STATIC_URL = "static/"
STATIC_ROOT = BASE_DIR / "staticfiles"

# Загружаемые файлы (логотипы компаний). Локальный диск; переход на S3/MinIO - этап 5.
MEDIA_ROOT = Path(env("MEDIA_ROOT") or BASE_DIR / "media")
MEDIA_URL = env("MEDIA_URL") or "/media/"
# Файлы и каталоги читаемы nginx (другой пользователь) независимо от umask gunicorn.
FILE_UPLOAD_PERMISSIONS = 0o644
FILE_UPLOAD_DIRECTORY_PERMISSIONS = 0o755

REST_FRAMEWORK = {
    "DEFAULT_AUTHENTICATION_CLASSES": [
        "apps.core.auth.CompanyJWTAuthentication",
    ],
    "DEFAULT_PERMISSION_CLASSES": [
        "rest_framework.permissions.IsAuthenticated",
        "apps.billing.permissions.SubscriptionGate",
    ],
    "EXCEPTION_HANDLER": "apps.core.exceptions.api_exception_handler",
    # публичный эндпоинт оформления экрана входа; лимит на IP
    "DEFAULT_THROTTLE_RATES": {
        "branding": env("BRANDING_THROTTLE_RATE", "60/min"),
        "member_attach": env("MEMBER_ATTACH_THROTTLE_RATE", "20/min"),
        "password_change": env("PASSWORD_CHANGE_THROTTLE_RATE", "5/min"),
        # документы: на компанию (загрузка шаблонов и тяжёлая конвертация в PDF)
        "document_upload": env("DOCUMENT_UPLOAD_THROTTLE_RATE", "30/hour"),
        "document_pdf": env("DOCUMENT_PDF_THROTTLE_RATE", "30/min"),
        # вход: по нормализованному логину, а не по IP (за внешним прокси IP общий)
        "login": env("THROTTLE_LOGIN", "10/minute"),
        "totp": env("THROTTLE_TOTP", "5/minute"),
        "password_setup": env("THROTTLE_PASSWORD_SETUP", "10/minute"),
    },
}
# Продакшен/serverless: только JSON (BrowsableAPI тянет статику и шаблоны, которых там нет).
if SERVERLESS or not DEBUG:
    REST_FRAMEWORK["DEFAULT_RENDERER_CLASSES"] = ["rest_framework.renderers.JSONRenderer"]

# срок одноразовой ссылки первоначальной установки пароля (секунды); по умолчанию 2 часа
PASSWORD_RESET_TIMEOUT = int(env("PASSWORD_SETUP_TIMEOUT_SECONDS", "7200"))

SIMPLE_JWT = {
    "ACCESS_TOKEN_LIFETIME": timedelta(minutes=int(env("JWT_ACCESS_MINUTES", "30"))),
    "REFRESH_TOKEN_LIFETIME": timedelta(days=int(env("JWT_REFRESH_DAYS", "14"))),
}

# X-Forwarded-For учитывается (для IP в журнале аудита) только за доверенным прокси.
# Прокси ОБЯЗАН перезаписывать (а не дополнять) X-Forwarded-For: берётся первый адрес,
# иначе клиент подделает IP своим заголовком.
TRUST_PROXY_HEADERS = env_bool("TRUST_PROXY_HEADERS", False)

CORS_ALLOWED_ORIGINS = env_list("CORS_ALLOWED_ORIGINS", "http://localhost:5173")

REDIS_URL = env("REDIS_URL", "redis://127.0.0.1:6379/0")

# Кэш (и счётчики throttle) общий для воркеров только с REDIS_URL; без него - LocMem на процесс
# (разработка и тесты). В продакшене REDIS_URL ОБЯЗАТЕЛЕН.
if os.environ.get("REDIS_URL"):
    CACHES = {
        "default": {
            "BACKEND": "django.core.cache.backends.redis.RedisCache",
            "LOCATION": os.environ["REDIS_URL"],
        }
    }
else:
    CACHES = {"default": {"BACKEND": "django.core.cache.backends.locmem.LocMemCache"}}
CELERY_BROKER_URL = env("CELERY_BROKER_URL", REDIS_URL)
CELERY_RESULT_BACKEND = env("CELERY_RESULT_BACKEND", REDIS_URL)
CELERY_TIMEZONE = TIME_ZONE

# --- Продакшен (DEBUG=false) -------------------------------------------------------------
# Статика собирается collectstatic в STATIC_ROOT и раздаётся nginx; медиа (MEDIA_ROOT) - тоже nginx.
BEHIND_TLS_PROXY = env_bool("DJANGO_BEHIND_TLS_PROXY", False)
# Редирект http->https в Django. По умолчанию как BEHIND_TLS_PROXY (VPS не меняется). false -
# только для демо на Vercel, где TLS завершает платформа (см. docs/ops/VERCEL.md).
SSL_REDIRECT = env_bool("DJANGO_SSL_REDIRECT", BEHIND_TLS_PROXY)
CSRF_TRUSTED_ORIGINS = env_list("DJANGO_CSRF_TRUSTED_ORIGINS", "")

if not DEBUG:
    # Доверять X-Forwarded-Proto можно только за НАШИМ nginx, который его перезаписывает.
    if BEHIND_TLS_PROXY:
        SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")
        # nginx редиректит сам; здесь страховка. Healthcheck контейнера ходит по http напрямую.
        if SSL_REDIRECT:
            SECURE_SSL_REDIRECT = True
            SECURE_REDIRECT_EXEMPT = [r"^api/health/$"]
    SESSION_COOKIE_SECURE = BEHIND_TLS_PROXY
    CSRF_COOKIE_SECURE = BEHIND_TLS_PROXY
    SESSION_COOKIE_HTTPONLY = True
    SECURE_CONTENT_TYPE_NOSNIFF = True
    SECURE_REFERRER_POLICY = "same-origin"
    X_FRAME_OPTIONS = "DENY"
    # HSTS по умолчанию выключен, пока TLS не подтверждён (ошибка закрепляется в браузерах).
    SECURE_HSTS_SECONDS = int(env("DJANGO_HSTS_SECONDS", "0"))
    SECURE_HSTS_INCLUDE_SUBDOMAINS = env_bool("DJANGO_HSTS_INCLUDE_SUBDOMAINS", False)
    SECURE_HSTS_PRELOAD = env_bool("DJANGO_HSTS_PRELOAD", False)

# Предзагрузка HSTS (preload) - осознанное решение владельца домена, не включается по умолчанию.
# DJANGO_SILENCED_CHECKS - только для CI-примера (HSTS по умолчанию выключен, см. RUNBOOK).
SILENCED_SYSTEM_CHECKS = ["security.W021", *env_list("DJANGO_SILENCED_CHECKS")]

# Sentry: инициализируется в config/observability.py только при заданном SENTRY_DSN.
SENTRY_DSN = env("SENTRY_DSN", "")
SENTRY_ENVIRONMENT = env("SENTRY_ENVIRONMENT", "production")
SENTRY_TRACES_SAMPLE_RATE = float(env("SENTRY_TRACES_SAMPLE_RATE", "0"))

# Логи в stderr контейнера (docker logs / json-file). По умолчанию Django в продакшене пишет
# ошибки запросов только в mail_admins (почты нет) - 500 остались бы без следа.
LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "formatters": {"plain": {"format": "%(asctime)s %(levelname)s %(name)s %(message)s"}},
    "handlers": {"console": {"class": "logging.StreamHandler", "formatter": "plain"}},
    "root": {"handlers": ["console"], "level": env("DJANGO_LOG_LEVEL", "INFO")},
    "loggers": {
        "django.request": {"handlers": ["console"], "level": "ERROR", "propagate": False},
    },
}
