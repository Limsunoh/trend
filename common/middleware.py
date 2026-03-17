"""
공통 미들웨어 (보안 헤더 등)
"""

import threading

# Gunicorn gevent 워커에서 동시 처리 중인 요청 수 (디버그/모니터링용).
# 미들웨어에서 요청 진입 시 +1, 응답 후 -1. threading.Lock으로 동기화.
_active_requests = 0
_active_requests_lock = threading.Lock()


def get_active_requests_count():
    """현재 처리 중인 요청 개수 (워커 프로세스 내)."""
    with _active_requests_lock:
        return _active_requests


class ActiveRequestCountMiddleware:
    """
    동시 처리 요청 수를 세어 get_active_requests_count()로 조회 가능하게 함.
    Locust 등 부하 테스트 시 /api/debug/active-requests/ 로 확인용.
    """

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        global _active_requests
        with _active_requests_lock:
            _active_requests += 1
        try:
            return self.get_response(request)
        finally:
            with _active_requests_lock:
                _active_requests -= 1


class SecurityHeadersMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        response = self.get_response(request)
        response["Referrer-Policy"] = "strict-origin-when-cross-origin"
        return response
