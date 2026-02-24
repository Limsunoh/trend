"""
공통 HTTP 뷰 (health 등)
"""

from django.conf import settings
from django.http import FileResponse, Http404, JsonResponse

from common.health import run_health_checks


def serve_spa(request, path=""):
    """
    SPA(React) catch-all: index.html 반환.
    /api/, /admin/, /static/, /media/ 가 아닌 경로에서 index.html 제공.
    """
    index_path = settings.BASE_DIR / "frontend_dist" / "index.html"
    if not index_path.exists():
        raise Http404("Frontend not built")
    return FileResponse(
        index_path.open("rb"),
        content_type="text/html",
    )


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
