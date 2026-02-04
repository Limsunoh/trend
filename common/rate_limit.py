"""
조회 API용 Rate Limit (DRF Throttle)

기사/포스트/분석 결과 조회 API에 IP 기준 분당 요청 제한을 적용합니다.
Redis 기반 RateLimitService를 사용합니다.
"""
from rest_framework.throttling import BaseThrottle

from common.redis_services import RateLimitService


# 조회 API: IP당 분당 120회 (평균 2회/초)
READ_API_MAX_REQUESTS = 120
READ_API_WINDOW_SECONDS = 60


def _get_client_ip(request):
    """X-Forwarded-For 또는 REMOTE_ADDR에서 클라이언트 IP 반환"""
    xff = (request.META.get('HTTP_X_FORWARDED_FOR') or '').strip()
    if xff:
        return xff.split(',')[0].strip() or request.META.get('REMOTE_ADDR', '0.0.0.0')
    return request.META.get('REMOTE_ADDR', '0.0.0.0')


class ReadAPIThrottle(BaseThrottle):
    """
    기사·포스트·분석 결과 조회 API용 Throttle.
    IP당 분당 READ_API_MAX_REQUESTS회 제한, 초과 시 429 + Retry-After.
    """
    scope = 'api_read'
    rate_limit_service = None  # lazy init

    def _get_service(self):
        if ReadAPIThrottle.rate_limit_service is None:
            ReadAPIThrottle.rate_limit_service = RateLimitService()
        return ReadAPIThrottle.rate_limit_service

    def get_cache_key(self, request, view):
        """Throttle 식별자: api_read:{ip}"""
        ip = _get_client_ip(request)
        return f"api_read:{ip}"

    def allow_request(self, request, view):
        key = self.get_cache_key(request, view)
        service = self._get_service()
        result = service.check_rate_limit(
            key,
            max_requests=READ_API_MAX_REQUESTS,
            window_seconds=READ_API_WINDOW_SECONDS,
        )
        if result['allowed']:
            return True
        # 초과 시 wait()에서 Retry-After용 남은 초 저장 (timezone 무관)
        status = service.get_rate_limit_status(key)
        self._wait_seconds = max(0, status.get('reset_in_seconds', 0) or 0)
        return False

    def wait(self):
        """429 응답 시 Retry-After(초) 반환"""
        if not hasattr(self, '_wait_seconds'):
            return None
        return self._wait_seconds if self._wait_seconds > 0 else None
