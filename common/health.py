"""
Health check: DB, Redis, Celery 상태 확인

/api/health/ 에서 사용. 각 의존성별로 "ok" / "error" 반환.
"""

from django.db import connection

from common.redis_services import RedisService


def check_db() -> str:
    """PostgreSQL 연결 확인. 성공 시 'ok', 실패 시 'error'."""
    try:
        with connection.cursor() as cursor:
            cursor.execute("SELECT 1")
        return "ok"
    except Exception:
        return "error"


def check_redis() -> str:
    """Redis 연결 확인 (PING). 성공 시 'ok', 실패 시 'error'."""
    try:
        client = RedisService().client
        client.ping()
        return "ok"
    except Exception:
        return "error"


def check_celery(timeout: int = 2) -> str:
    """
    Celery 워커 응답 확인 (inspect ping).
    최소 1명 워커가 응답하면 'ok', 없거나 예외 시 'error'.
    """
    try:
        from trend_analyzer.celery import app as celery_app

        inspect = celery_app.control.inspect(timeout=timeout)
        result = inspect.ping()
        if result and any(result.values()):
            return "ok"
        return "error"
    except Exception:
        return "error"


def run_health_checks() -> dict:
    """
    DB / Redis / Celery 체크 실행.
    Returns:
        {"db": "ok"|"error", "redis": "ok"|"error", "celery": "ok"|"error"}
    """
    return {
        "db": check_db(),
        "redis": check_redis(),
        "celery": check_celery(),
    }
