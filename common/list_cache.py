"""
목록 API용 Redis 캐시 유틸

- 요청 경로 + 쿼리스트링으로 캐시 키를 만들고, list 응답을 캐시해 DB/직렬화 부하를 줄입니다.
- 각 ViewSet의 list()에서 캐시 조회 → 없으면 super().list() 호출 후 캐시 저장 패턴으로 사용합니다.
"""

from django.conf import settings
from django.core.cache import cache


def make_list_cache_key(request, prefix: str) -> str:
    """
    목록 API 캐시 키 생성.

    같은 path + 같은 쿼리 파라미터면 같은 키가 나와야 하므로,
    쿼리스트링을 정렬한 뒤 path와 합쳐서 키로 씁니다.

    Args:
        request: DRF Request (path, QUERY_STRING 사용)
        prefix: 캐시 네임스페이스 (예: "dashboard:news", "analyzer:results")

    Returns:
        예: "list:dashboard:news:/api/dashboard/news/:page=1&page_size=20"
    """
    raw_qs = request.META.get("QUERY_STRING", "")
    # 파라미터 순서가 달라도 같은 키가 되도록 정렬 (page=1&page_size=20 === page_size=20&page=1)
    sorted_params = "&".join(sorted(raw_qs.split("&"))) if raw_qs else ""
    return f"list:{prefix}:{request.path}:{sorted_params}"


def get_list_cache_ttl() -> int:
    """
    목록 API 캐시 TTL(초). settings.LIST_API_CACHE_TTL 사용.
    환경변수 LIST_API_CACHE_TTL로 오버라이드 가능 (기본 60초).
    """
    return getattr(settings, "LIST_API_CACHE_TTL", 60)


def get_cached_list_response(request, prefix: str):
    """
    캐시에 저장된 목록 응답 데이터가 있으면 반환, 없으면 None.

    Returns:
        캐시 hit 시 직렬화된 응답 dict (Response(data)로 그대로 반환 가능), miss 시 None
    """
    key = make_list_cache_key(request, prefix)
    return cache.get(key)


def set_cached_list_response(request, prefix: str, data: dict) -> None:
    """
    목록 API 응답 데이터를 캐시에 저장.
    """
    key = make_list_cache_key(request, prefix)
    ttl = get_list_cache_ttl()
    cache.set(key, data, ttl)
