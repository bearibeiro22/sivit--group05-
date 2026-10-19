"""Configuração do portal SIVIT.

Regra desta UC: a imagem é imutável, a configuração vem do ambiente.
Nada aqui deve ter de mudar para passar de desenvolvimento a produção.
"""
import os
from pathlib import Path
from urllib.parse import urlparse

BASE_DIR = Path(__file__).resolve().parent.parent

SECRET_KEY = os.environ.get("DJANGO_SECRET_KEY", "dev-inseguro")
DEBUG = os.environ.get("DJANGO_DEBUG", "0") == "1"
ALLOWED_HOSTS = os.environ.get("DJANGO_ALLOWED_HOSTS", "*").split(",")

INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "rest_framework",
    "rest_framework.authtoken",
    "drf_spectacular",
    "vigilancia",
]

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    # Extensão E4: injeta latência quando LATENCIA_MS > 0.
    "vigilancia.middleware.LatenciaArtificialMiddleware",
    "vigilancia.middleware.DropResponseMiddleware",
]

ROOT_URLCONF = "config.urls"
WSGI_APPLICATION = "config.wsgi.application"

TEMPLATES = [{
    "BACKEND": "django.template.backends.django.DjangoTemplates",
    "DIRS": [BASE_DIR / "vigilancia" / "templates"],
    "APP_DIRS": True,
    "OPTIONS": {"context_processors": [
        "django.template.context_processors.request",
        "django.contrib.auth.context_processors.auth",
        "django.contrib.messages.context_processors.messages",
    ]},
}]


def bd_do_ambiente(url):
    """Traduz uma DATABASE_URL para o dicionário do Django.

    Feito à mão, sem dj-database-url: são dez linhas e evita explicar uma
    dependência que não é o assunto da aula.
    """
    u = urlparse(url)
    return {
        "ENGINE": "django.db.backends.postgresql",
        "NAME": u.path.lstrip("/"),
        "USER": u.username or "",
        "PASSWORD": u.password or "",
        "HOST": u.hostname or "",
        "PORT": str(u.port or 5432),
        "CONN_MAX_AGE": int(os.environ.get("CONN_MAX_AGE", "60")),
        # Toda a operação de rede precisa de um prazo. Sem este, uma ligação
        # nova a uma BD em baixo pode ficar pendurada 75 s, e o Gunicorn mata o
        # worker aos 30: uma falha rápida torna-se uma falha lenta (TP2 §2.4).
        "OPTIONS": {"connect_timeout": int(os.environ.get("BD_CONNECT_TIMEOUT", "3"))},
    }


DATABASES = {
    "default": bd_do_ambiente(
        os.environ.get("DATABASE_URL", "postgres://sivit:devpass@sivitDB:5432/sivit")),
}

# TP7: se existir REPLICA_URL, acrescenta-se a segunda ligação e o router.
if os.environ.get("REPLICA_URL"):
    DATABASES["replica"] = bd_do_ambiente(os.environ["REPLICA_URL"])
    DATABASE_ROUTERS = ["vigilancia.routers.RouterLeituraEscrita"]

# TP2-E3: com várias réplicas do portal, a sessão em memória perde-se.
SESSION_ENGINE = os.environ.get("SESSION_ENGINE",
                                "django.contrib.sessions.backends.db")

LANGUAGE_CODE = "pt-pt"
TIME_ZONE = "Europe/Lisbon"
USE_I18N = True
USE_TZ = True

STATIC_URL = "/static/"
STATIC_ROOT = "/var/www/static"

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "handlers": {"consola": {"class": "logging.StreamHandler"}},
    "root": {"handlers": ["consola"], "level": os.environ.get("LOG_LEVEL", "INFO")},
}

REST_FRAMEWORK = {
    "DEFAULT_SCHEMA_CLASS": "drf_spectacular.openapi.AutoSchema",
}
SPECTACULAR_SETTINGS = {"TITLE": "SIVIT API", "VERSION": "1.0.0"}

# TP3-E4: autenticacao e throttling para maquinas.
REST_FRAMEWORK.update({
    # So tokens: as sessoes humanas (admin) nao autenticam a API.
    "DEFAULT_AUTHENTICATION_CLASSES": ["rest_framework.authentication.TokenAuthentication"],
    "DEFAULT_PERMISSION_CLASSES": ["rest_framework.permissions.IsAuthenticated"],
    # Um gateway = um utilizador = um token = uma quota (bulkhead, B8).
    "DEFAULT_THROTTLE_CLASSES": ["rest_framework.throttling.UserRateThrottle"],
    "DEFAULT_THROTTLE_RATES": {"user": os.environ.get("THROTTLE_RATE", "120/min")},
})
SPECTACULAR_SETTINGS = {
    "TITLE": "SIVIT API",
    "DESCRIPTION": "API de ingestao e consulta de leituras de dispositivos.",
    "VERSION": "1.0.0",
    "SERVE_INCLUDE_SCHEMA": False,
    "SCHEMA_PATH_PREFIX": r"/api/v[0-9]",
}
# O contador do throttling tem de ser partilhado pelos workers do Gunicorn:
# a cache por omissao (memoria local) daria a cada worker a sua propria quota.
CACHES = {"default": {"BACKEND": "django.core.cache.backends.db.DatabaseCache",
                      "LOCATION": "cache_throttle"}}
