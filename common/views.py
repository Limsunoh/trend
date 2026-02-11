"""
공통 HTTP 뷰 (health 등)
"""

from django.http import JsonResponse

from common.health import run_health_checks


def health_view(request):
    """
    GET /api/health/
    DB, Redis, Celery 상태 확인. 전부 ok면 200, 하나라도 error면 503.
    Rate limit 미적용.
    """
    if request.method != "GET":
        return JsonResponse({"detail": "Method not allowed"}, status=405)

    checks = run_health_checks()
    all_ok = all(v == "ok" for v in checks.values())
    status_code = 200 if all_ok else 503
    body = {
        "status": "ok" if all_ok else "degraded",
        "checks": checks,
    }
    return JsonResponse(body, status=status_code)
