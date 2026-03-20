"""
Django settings for trend_analyzer project.
"""

import os
from datetime import timedelta
from pathlib import Path

import sentry_sdk
from dotenv import load_dotenv
from sentry_sdk.integrations.django import DjangoIntegration

from common.sentry_dual_dsn import DualDsnsTransport

# Load environment variables
load_dotenv(override=True)

# 로컬 PostgreSQL(Windows)이 UTF-8이 아닌 응답을 보낼 때 UnicodeDecodeError 방지
# libpq가 연결 시 UTF-8을 쓰도록 강제
if "PGCLIENTENCODING" not in os.environ:
    os.environ["PGCLIENTENCODING"] = "UTF8"

# Sentry (에러 수집) - DSN 있으면 초기화. 두 번째 DSN 있으면 동일 이벤트를 두 프로젝트로 전송.
_sentry_dsn = os.getenv("SENTRY_DSN", "").strip()
if _sentry_dsn:
    sentry_sdk.init(
        dsn=_sentry_dsn,
        integrations=[DjangoIntegration()],
        environment=os.getenv("SENTRY_ENVIRONMENT", "development"),
        traces_sample_rate=0.1,
        send_default_pii=False,
        transport=DualDsnsTransport,
    )

# Build paths inside the project like this: BASE_DIR / 'subdir'.
BASE_DIR = Path(__file__).resolve().parent.parent

# loaddata가 찾는 fixture 디렉터리 (프로젝트 루트의 fixtures/ → Docker에서는 /app/fixtures)
FIXTURE_DIRS = [BASE_DIR / "fixtures"]

# SECURITY WARNING: keep the secret key used in production secret!
SECRET_KEY = os.getenv("SECRET_KEY", "django-insecure-change-this-in-production")

# SECURITY WARNING: don't run with debug turned on in production!
DEBUG = os.getenv("DEBUG", "True") == "True"

ALLOWED_HOSTS = ["*"]

CSRF_TRUSTED_ORIGINS = [
    "http://3.37.203.226:8000",
    "http://3.37.203.226",
    "http://localhost:8000",
    "http://127.0.0.1:8000",
    "https://3.37.203.226:8000",
    "https://3.37.203.226",
    "http://aitrend.홈페이지.한국",
    "https://aitrend.홈페이지.한국",
    "http://www.aitrend.홈페이지.한국",
    "https://www.aitrend.홈페이지.한국",
]

# 보안 헤더 (SecurityMiddleware / XFrameOptionsMiddleware 가 적용)
SECURE_CONTENT_TYPE_NOSNIFF = True  # X-Content-Type-Options: nosniff
SECURE_BROWSER_XSS_FILTER = True  # X-XSS-Protection: 1; mode=block
X_FRAME_OPTIONS = "DENY"  # X-Frame-Options: DENY

# Application definition

INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    # Third party apps
    "rest_framework",
    "drf_spectacular",  # Swagger/OpenAPI
    "corsheaders",
    "django_celery_beat",
    "django_celery_results",
    "storages",
    # Local apps
    "data_collector",
    "analyzer",
    "dashboard",
    "user_qa",
]

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "whitenoise.middleware.WhiteNoiseMiddleware",
    "common.middleware.ActiveRequestCountMiddleware",  # 동시 요청 수 (디버그용)
    "common.middleware.SecurityHeadersMiddleware",  # Referrer-Policy
    "corsheaders.middleware.CorsMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]

ROOT_URLCONF = "trend_analyzer.urls"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [BASE_DIR / "templates"],
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

WSGI_APPLICATION = "trend_analyzer.wsgi.application"


# Database
# https://docs.djangoproject.com/en/4.2/ref/settings/#databases


def _safe_db_str(value: str) -> str:
    """로컬 Windows 등에서 .env 인코딩(CP949)으로 인한 UnicodeDecodeError 방지."""
    if not value:
        return value
    if isinstance(value, bytes):
        return value.decode("utf-8", errors="replace")
    # str도 UTF-8로 정규화 (psycopg2 연결 시 decode 오류 방지)
    return value.encode("utf-8", errors="replace").decode("utf-8")


def _db_options():
    opts = {
        "connect_timeout": 60,
        "client_encoding": "UTF8",
        "options": "-c client_encoding=UTF8",
    }
    ssl_mode = os.getenv("DB_SSL_MODE", "").strip()
    if ssl_mode:
        opts["sslmode"] = ssl_mode
    ssl_root_cert = os.getenv("DB_SSL_ROOT_CERT", "").strip()
    if ssl_root_cert:
        opts["sslrootcert"] = ssl_root_cert
    return opts


DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.postgresql",
        "NAME": _safe_db_str(os.getenv("DB_NAME", "trend_db")),
        "USER": _safe_db_str(os.getenv("DB_USER", "team_user")),
        "PASSWORD": _safe_db_str(os.getenv("DB_PASSWORD", "")),
        "HOST": _safe_db_str(os.getenv("DB_HOST", "localhost")),
        "PORT": _safe_db_str(os.getenv("DB_PORT", "5432")),
        "OPTIONS": _db_options(),
    }
}


# Password validation
# https://docs.djangoproject.com/en/4.2/ref/settings/#auth-password-validators

AUTH_PASSWORD_VALIDATORS = [
    {
        "NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator",
    },
    {
        "NAME": "django.contrib.auth.password_validation.MinimumLengthValidator",
    },
    {
        "NAME": "django.contrib.auth.password_validation.CommonPasswordValidator",
    },
    {
        "NAME": "django.contrib.auth.password_validation.NumericPasswordValidator",
    },
]


# Internationalization
# https://docs.djangoproject.com/en/4.2/topics/i18n/

LANGUAGE_CODE = "ko-kr"

TIME_ZONE = "Asia/Seoul"

USE_I18N = True

USE_TZ = True


# Static files (CSS, JavaScript, Images)
# https://docs.djangoproject.com/en/4.2/howto/static-files/

STATIC_URL = "/static/"
STATIC_ROOT = BASE_DIR / "staticfiles"
_STATIC_DIRS = [BASE_DIR / "static"] if (BASE_DIR / "static").exists() else []
_FRONTEND_DIST = BASE_DIR / "frontend_dist"
if _FRONTEND_DIST.exists():
    STATICFILES_DIRS = [*_STATIC_DIRS, ("frontend", str(_FRONTEND_DIST))]
else:
    STATICFILES_DIRS = _STATIC_DIRS

MEDIA_URL = "/media/"
MEDIA_ROOT = BASE_DIR / "media"

# Default primary key field type
# https://docs.djangoproject.com/en/4.2/ref/settings/#default-auto-field

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

# Redis Configuration
REDIS_HOST = os.getenv("REDIS_HOST", "localhost")
REDIS_PORT = os.getenv("REDIS_PORT", "6379")
REDIS_DB = os.getenv("REDIS_DB", "0")
ANALYSIS_CACHE_TTL_SECONDS = int(os.getenv("ANALYSIS_CACHE_TTL_SECONDS", str(6 * 3600)))

CACHES = {
    "default": {
        "BACKEND": "django.core.cache.backends.redis.RedisCache",
        "LOCATION": f"redis://{REDIS_HOST}:{REDIS_PORT}/{REDIS_DB}",
    }
}

# 목록 API Redis 캐시 TTL (초).
LIST_API_CACHE_TTL = int(os.getenv("LIST_API_CACHE_TTL", "900"))

# Celery Configuration
CELERY_BROKER_URL = f"redis://{REDIS_HOST}:{REDIS_PORT}/{REDIS_DB}"
CELERY_RESULT_BACKEND = f"redis://{REDIS_HOST}:{REDIS_PORT}/{REDIS_DB}"
CELERY_ACCEPT_CONTENT = ["json"]
CELERY_TASK_SERIALIZER = "json"
CELERY_RESULT_SERIALIZER = "json"
CELERY_TIMEZONE = TIME_ZONE
CELERY_BEAT_SCHEDULER = "django_celery_beat.schedulers:DatabaseScheduler"

# ✅ 임베딩 태스크를 전용 큐로 분리 (ChromaDB 동시 쓰기 방지)
# 임베딩 worker: celery -A trend_analyzer worker --pool=solo --queues=embedding -c 1
# 수집 worker:   celery -A trend_analyzer worker --pool=prefork --queues=celery -c 4
CELERY_TASK_ROUTES = {
    "user_qa.tasks.embed_recent_news_articles_task": {"queue": "embedding"},
    "user_qa.tasks.embed_recent_social_posts_task": {"queue": "embedding"},
}

# Celery Beat Schedule
# data_collector와 analyzer 태스크를 함께 스케줄링할 수 있습니다.
#
# CELERY_BEAT_SCHEDULE = {
#     # 데이터 수집 (예: 1시간마다)
#     'collect-all-news': {
#         'task': 'data_collector.collect_all_rss_news_task',
#         'schedule': timedelta(hours=1),
#     },
#     'collect-all-social': {
#         'task': 'data_collector.collect_all_social_media_task',
#         'schedule': timedelta(hours=1),
#     },
#     # 데이터 수집 후 분석 (예: 6시간마다)
#     'analyze-time-lag': {
#         'task': 'analyzer.analyze_time_lag_task',
#         'schedule': timedelta(hours=6),
#     },
#     'detect-surge-keywords': {
#         'task': 'analyzer.detect_surge_keywords_task',
#         'schedule': timedelta(hours=6),
#     },
#     'analyze-trend-synchronization': {
#         'task': 'analyzer.analyze_trend_synchronization_task',
#         'schedule': timedelta(hours=6),
#     },
#     'analyze-hourly-trends': {
#         'task': 'analyzer.analyze_hourly_trends_task',
#         'schedule': timedelta(hours=6),
#     },
# }

CELERY_BEAT_SCHEDULE = {
    # ✅ 안전망: 자동 임베딩 트리거가 실패한 경우를 대비한 주기적 임베딩
    # check_session_completion에서 이벤트 기반으로 트리거하지만,
    # 네트워크 오류/워커 다운 등으로 놓친 데이터를 30분마다 소급 처리
    "embed-unprocessed-news": {
        "task": "user_qa.tasks.embed_recent_news_articles_task",
        "schedule": timedelta(minutes=30),
        "kwargs": {
            "since": None,
            "collection": None,
            "limit": 5000,
        },
        "options": {"queue": "embedding"},
    },
    "embed-unprocessed-social": {
        "task": "user_qa.tasks.embed_recent_social_posts_task",
        "schedule": timedelta(minutes=30),
        "kwargs": {
            "since": None,
            "collection": None,
            "limit": 5000,
        },
        "options": {"queue": "embedding"},
    },
}

# AWS S3 Configuration
USE_S3 = os.getenv("USE_S3", "False") == "True"

if USE_S3:
    AWS_ACCESS_KEY_ID = os.getenv("AWS_ACCESS_KEY_ID")
    AWS_SECRET_ACCESS_KEY = os.getenv("AWS_SECRET_ACCESS_KEY")
    AWS_STORAGE_BUCKET_NAME = os.getenv("AWS_STORAGE_BUCKET_NAME")
    AWS_S3_REGION_NAME = os.getenv("AWS_S3_REGION_NAME", "ap-northeast-2")
    AWS_S3_CUSTOM_DOMAIN = os.getenv(
        "AWS_S3_CUSTOM_DOMAIN", f"{AWS_STORAGE_BUCKET_NAME}.s3.amazonaws.com"
    )
    AWS_S3_OBJECT_PARAMETERS = {
        "CacheControl": "max-age=86400",
    }
    AWS_DEFAULT_ACL = "public-read"

    # Static files
    STATICFILES_STORAGE = "storages.backends.s3boto3.S3Boto3Storage"
    DEFAULT_FILE_STORAGE = "storages.backends.s3boto3.S3Boto3Storage"

    STATIC_URL = f"https://{AWS_S3_CUSTOM_DOMAIN}/static/"
    MEDIA_URL = f"https://{AWS_S3_CUSTOM_DOMAIN}/media/"

# CDN Configuration
CDN_DOMAIN = os.getenv("CDN_DOMAIN", "")

# REST Framework
REST_FRAMEWORK = {
    "DEFAULT_PAGINATION_CLASS": "rest_framework.pagination.PageNumberPagination",
    "PAGE_SIZE": 100,
    "DEFAULT_RENDERER_CLASSES": [
        "rest_framework.renderers.JSONRenderer",
    ],
    "DEFAULT_PARSER_CLASSES": [
        "rest_framework.parsers.JSONParser",
    ],
    "DEFAULT_SCHEMA_CLASS": "drf_spectacular.openapi.AutoSchema",
}

# drf-spectacular (Swagger) 설정
SPECTACULAR_SETTINGS = {
    "TITLE": "Trend Analyzer API",
    "DESCRIPTION": "뉴스 데이터 수집 및 트렌드 분석 API",
    "VERSION": "1.0.0",
    "SERVE_INCLUDE_SCHEMA": False,
    "COMPONENT_SPLIT_REQUEST": True,
    "SCHEMA_PATH_PREFIX": "/api/",
    # 성능 최적화 옵션
    "SCHEMA_COERCE_PATH_PK": True,  # PK를 경로에서 자동 변환
    "SCHEMA_COERCE_METHOD_NAMES": {
        "retrieve": "read",
        "list": "read",
    },
    # 스키마 생성 최적화
    "DEFAULT_GENERATOR_CLASS": "drf_spectacular.generators.SchemaGenerator",
    # 예제 데이터 생성 최소화 (큰 JSON 필드 때문에)
    "COMPONENT_NO_READ_ONLY_REQUIRED": True,
    "ENUM_NAME_OVERRIDES": {},
    # 스키마 생성 시 예제 크기 제한
    "SCHEMA_PATH_PREFIX_TRIM": False,  # False로 변경: /api/ 접두사 유지
    # 큰 필드 처리 최적화
    "OAS_VERSION": "3.0.3",
    # 예제 데이터 생성 비활성화 (성능 향상)
    "DISABLE_ERRORS_AND_WARNINGS": True,
    # 스키마 생성 시 타임아웃 방지
    "APPEND_COMPONENTS": {
        "securitySchemes": {
            "basicAuth": {
                "type": "http",
                "scheme": "basic",
            }
        }
    },
}

# CORS Settings
CORS_ALLOWED_ORIGINS = [
    "http://localhost:3000",
    "http://localhost:8000",
    "https://127.0.0.1:8000",
    "https://127.0.0.1:3000",
]

CORS_ALLOW_ALL_ORIGINS = DEBUG

# RAG & Vector DB Configuration
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "")
OPENAI_MODEL = os.getenv("OPENAI_MODEL", "gpt-4o")
OPENAI_TEMPERATURE = float(os.getenv("OPENAI_TEMPERATURE", "0.2"))
# gpt-5는 reasoning 토큰이 output에서 차감되므로 충분히 높게 설정
OPENAI_MAX_OUTPUT_TOKENS = int(os.getenv("OPENAI_MAX_OUTPUT_TOKENS", "1500"))
EMBEDDING_MODEL = os.getenv(
    "EMBEDDING_MODEL", "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2"
)
VECTOR_DB_PATH = os.getenv("VECTOR_DB_PATH", BASE_DIR / "vector_db")
CHROMA_PERSIST_DIR = os.getenv("CHROMA_PERSIST_DIR", BASE_DIR / "chroma_db")

# RAG Quality Gating Thresholds
# L2² 거리 기준 (정규화 임베딩: L2² = 2*(1-cos_sim))
# 1.05 → cos_sim 0.475 미만만 차단 (진정한 무관 문서)
RAG_HARD_DISTANCE_THRESHOLD = float(os.getenv("RAG_HARD_DISTANCE_THRESHOLD", "1.05"))
# 평균 거리 0.65 초과 → LLM에 "low" 시그널
RAG_WEAK_RELEVANCE_THRESHOLD = float(os.getenv("RAG_WEAK_RELEVANCE_THRESHOLD", "0.65"))
RAG_NEWS_DISTANCE_THRESHOLD = float(os.getenv("RAG_NEWS_DISTANCE_THRESHOLD", "0.90"))
RAG_COMMUNITY_DISTANCE_THRESHOLD = float(
    os.getenv("RAG_COMMUNITY_DISTANCE_THRESHOLD", "0.90")
)

# Logging Configuration
LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "formatters": {
        "verbose": {
            "format": "[{levelname}] {asctime} {module} {message}",
            "style": "{",
        },
        "simple": {
            "format": "[{levelname}] {message}",
            "style": "{",
        },
    },
    "handlers": {
        "console": {
            "class": "logging.StreamHandler",
            "formatter": "verbose",
        },
    },
    "root": {
        "handlers": ["console"],
        "level": "INFO",
    },
    "loggers": {
        "data_collector": {
            "handlers": ["console"],
            "level": "DEBUG",  # DEBUG 레벨로 설정하여 상세 로그 확인
            "propagate": False,
        },
        "user_qa": {
            "handlers": ["console"],
            "level": "DEBUG",
            "propagate": False,
        },
        "django": {
            "handlers": ["console"],
            "level": "INFO",
            "propagate": False,
        },
    },
}
