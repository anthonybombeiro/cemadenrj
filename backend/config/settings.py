"""
Configuração do projeto Painel Meteorológico/Hidrológico CEMADEN-RJ.

Mantida deliberadamente simples (sem GeoDjango/PostGIS) para rodar sem
dependências nativas pesadas (GDAL/GEOS) tanto em desenvolvimento local
no Windows quanto no servidor HostGator. Localização das estações é
guardada como latitude/longitude (float) — suficiente para mapa e para
filtros por distância feitos em Python. Se no futuro for necessário
PostGIS para consultas geoespaciais avançadas, é uma migração incremental.
"""

import os
from pathlib import Path

import dj_database_url
from dotenv import load_dotenv

# PyMySQL no lugar de mysqlclient: o driver "nativo" do Django para MySQL
# (mysqlclient) precisa compilar contra headers do libmysqlclient, que não
# existem em hospedagem compartilhada sem root (como o HostGator). PyMySQL
# é puro Python e esse shim faz o Django enxergá-lo como se fosse o
# mysqlclient. Só importa se o pacote estiver instalado — não quebra em
# ambientes que usam só SQLite/Postgres.
try:
    import pymysql

    pymysql.install_as_MySQLdb()
except ImportError:
    pass

BASE_DIR = Path(__file__).resolve().parent.parent
load_dotenv(BASE_DIR / ".env")

SECRET_KEY = os.environ.get("SECRET_KEY", "dev-only-insecure-key")
DEBUG = os.environ.get("DEBUG", "True") == "True"
ALLOWED_HOSTS = [
    h.strip() for h in os.environ.get("ALLOWED_HOSTS", "localhost,127.0.0.1").split(",") if h.strip()
]

INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "rest_framework",
    "corsheaders",
    "core",
    "api",
    "ingestion",
]

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "corsheaders.middleware.CorsMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]

ROOT_URLCONF = "config.urls"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.debug",
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
            ],
        },
    },
]

WSGI_APPLICATION = "config.wsgi.application"

DATABASE_URL = os.environ.get("DATABASE_URL", "").strip()
if DATABASE_URL:
    DATABASES = {"default": dj_database_url.parse(DATABASE_URL, conn_max_age=600)}
else:
    DATABASES = {
        "default": {
            "ENGINE": "django.db.backends.sqlite3",
            "NAME": BASE_DIR / "db.sqlite3",
        }
    }

AUTH_PASSWORD_VALIDATORS = [
    {"NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator"},
    {"NAME": "django.contrib.auth.password_validation.MinimumLengthValidator"},
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
    {"NAME": "django.contrib.auth.password_validation.NumericPasswordValidator"},
]

LANGUAGE_CODE = "pt-br"
TIME_ZONE = "America/Sao_Paulo"
USE_I18N = True
USE_TZ = True

STATIC_URL = "static/"
STATIC_ROOT = BASE_DIR / "staticfiles"

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

REST_FRAMEWORK = {
    "DEFAULT_PAGINATION_CLASS": "rest_framework.pagination.LimitOffsetPagination",
    "PAGE_SIZE": 200,
    "DEFAULT_PERMISSION_CLASSES": ["rest_framework.permissions.AllowAny"],
}

CORS_ALLOWED_ORIGINS = [
    o.strip() for o in os.environ.get("CORS_ALLOWED_ORIGINS", "http://localhost:3000").split(",") if o.strip()
]

# --- Ingestão de dados de fontes externas -----------------------------------
REDIS_URL = os.environ.get("REDIS_URL", "redis://localhost:6379/0")
CELERY_BROKER_URL = REDIS_URL
CELERY_RESULT_BACKEND = REDIS_URL
CELERY_TIMEZONE = TIME_ZONE

# Segredo compartilhado para o endpoint /api/ingest/readings/ — usado pelo
# worker do GitHub Actions (.github/workflows/scrape-inmet.yml) para enviar
# leituras raspadas com um Chrome real, já que o HostGator não tem Chrome.
# Gere um valor aleatório longo (ex: `openssl rand -hex 32`) e configure o
# MESMO valor aqui e no secret INGEST_SHARED_SECRET do repositório GitHub.
INGEST_SHARED_SECRET = os.environ.get("INGEST_SHARED_SECRET", "")

# Segredo compartilhado para o endpoint /api/admin/run/ — existe porque o
# HostGator (hospedagem compartilhada) não dá acesso a shell, então rodar
# `migrate`/`collectstatic`/ingestão precisa ser feito via HTTP (chamado
# manualmente na primeira vez, depois pelos Cron Jobs do cPanel). Gere um
# valor aleatório longo (ex: `openssl rand -hex 32`) — NUNCA reaproveitar o
# INGEST_SHARED_SECRET aqui, são segredos com poderes bem diferentes.
ADMIN_TRIGGER_SECRET = os.environ.get("ADMIN_TRIGGER_SECRET", "")

# Conta institucional CEMADEN-RJ na Plugfield (estações meteorológicas
# municipais). NUNCA colocar esses valores direto no código — só aqui,
# lidos do .env (que é gitignored).
PLUGFIELD_API_KEY = os.environ.get("PLUGFIELD_API_KEY", "")
PLUGFIELD_USERNAME = os.environ.get("PLUGFIELD_USERNAME", "")
PLUGFIELD_PASSWORD = os.environ.get("PLUGFIELD_PASSWORD", "")

# Chave PESSOAL do usuário (não a chave pública embutida no site), obtida
# via wunderground.com/member/api-keys (conta gratuita, autoatendimento).
# Usada só para consultar estações PWS específicas cujo código já é
# conhecido (passado pelas Defesas Civis municipais) — nunca para
# descobrir/enumerar a rede. Ver docs/fontes-de-dados.md.
WUNDERGROUND_API_KEY = os.environ.get("WUNDERGROUND_API_KEY", "")

INMET_API_TOKEN = os.environ.get("INMET_API_TOKEN", "")

# Solução temporária enquanto não há token da API: faz scraping da tabela
# pública (sem login) tempo.inmet.gov.br/TabelaEstacoes/{codigo} com um
# Chrome real via Selenium. Exige Google Chrome instalado na máquina que
# roda a ingestão — NÃO funciona no HostGator compartilhado (sem root para
# instalar Chrome). Ver docs/fontes-de-dados.md.
INMET_SCRAPE_ENABLED = os.environ.get("INMET_SCRAPE_ENABLED", "True") == "True"
INMET_SCRAPE_HEADLESS = os.environ.get("INMET_SCRAPE_HEADLESS", "True") == "True"
CEMADEN_NACIONAL_BASE_URL = os.environ.get(
    "CEMADEN_NACIONAL_BASE_URL", "http://150.163.255.240/CEMADEN/resources/parceiros"
)

LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "handlers": {"console": {"class": "logging.StreamHandler"}},
    "root": {"handlers": ["console"], "level": "INFO"},
    "loggers": {
        "ingestion": {"handlers": ["console"], "level": "INFO", "propagate": False},
    },
}
