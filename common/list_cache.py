"""
목록 API용 Redis 캐시 유틸

- 요청 경로 + 쿼리스트링으로 캐시 키를 만들고, list 응답을 캐시해 DB/직렬화 부하를 줄입니다.
- 각 ViewSet의 list()에서 캐시 조회 → 없으면 super().list() 호출 후 캐시 저장 패턴으로 사용합니다.
"""

from django.conf import settings
from django.core.cache import cache
from django.db.models import Count


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


def get_list_cache_ttl(prefix: str) -> int:
    """
    목록 API 캐시 TTL(초). prefix별로 settings의 그룹 TTL을 사용.

    - dashboard:news, dashboard:social → LIST_API_CACHE_TTL_DASHBOARD
    - analyzer:results, analyzer:analysis:* → LIST_API_CACHE_TTL_ANALYZER
    - user_qa:history → LIST_API_CACHE_TTL_QA_HISTORY
    - 그 외 → LIST_API_CACHE_TTL (폴백)
    """
    if prefix in ("dashboard:news", "dashboard:social"):
        return int(getattr(settings, "LIST_API_CACHE_TTL_DASHBOARD", 120))
    if prefix == "analyzer:results" or prefix.startswith("analyzer:analysis:"):
        return int(getattr(settings, "LIST_API_CACHE_TTL_ANALYZER", 600))
    if prefix == "user_qa:history":
        return int(getattr(settings, "LIST_API_CACHE_TTL_QA_HISTORY", 60))
    return int(getattr(settings, "LIST_API_CACHE_TTL", 60))


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
    ttl = get_list_cache_ttl(prefix)
    cache.set(key, data, ttl)


def get_or_set_cached_list_count(request, prefix: str, queryset) -> int:
    """
    DRF pagination의 queryset.count()와 동일한 값을 Redis에 캐시한다.
    목록 응답 캐시 miss 시에도 동일 요청 키로 count를 재사용해 COUNT(*) 부하를 줄인다.
    """
    key = make_list_cache_key(request, prefix) + ":count"
    cached = cache.get(key)
    if cached is not None:
        return int(cached)
    n = queryset.count()
    ttl = get_list_cache_ttl(prefix)
    cache.set(key, n, ttl)
    return n


def get_cached_source_id_count_map(model, namespace: str, source_ids: set) -> dict:
    """
    PI 상위 쿼리로 잡힌 source_id별 COUNT(id) 집계를 Redis에 캐시한다.
    (NewsArticleSerializer / BaseSocialMediaPostSerializer 의 GROUP BY 배치 집계)
    """
    if not source_ids:
        return {}
    sorted_ids = sorted(source_ids)
    key = f"source_id_counts:{namespace}:{','.join(map(str, sorted_ids))}"
    cached = cache.get(key)
    if cached is not None:
        return cached
    rows = (
        model.objects.filter(source_id__in=source_ids)
        .values("source_id")
        .annotate(total=Count("id"))
    )
    result = {row["source_id"]: row["total"] for row in rows}
    ttl = int(getattr(settings, "LIST_API_CACHE_TTL_DASHBOARD", 120))
    cache.set(key, result, ttl)
    return result
