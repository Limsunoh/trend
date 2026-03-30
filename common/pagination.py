"""
목록 API용 페이지네이션

ViewSet에 `list_cache_prefix`가 있으면 `common.list_cache.get_or_set_cached_list_count`로
pagination 직전의 queryset.count()를 Redis에 캐시해 PI에서 보이던 COUNT(*) 부하를 줄인다.
"""

from django.core.paginator import InvalidPage, Paginator
from rest_framework.exceptions import NotFound
from rest_framework.pagination import PageNumberPagination

from common.list_cache import get_or_set_cached_list_count


class CachedCountPaginator(Paginator):
    """queryset.count() 대신 미리 구한 total을 쓸 수 있는 Paginator."""

    def __init__(
        self,
        object_list,
        per_page,
        orphans=0,
        allow_empty_first_page=True,
        *,
        cached_count=None,
    ):
        self._cached_total = cached_count
        super().__init__(
            object_list,
            per_page,
            orphans=orphans,
            allow_empty_first_page=allow_empty_first_page,
        )

    @property
    def count(self):
        if self._cached_total is not None:
            return self._cached_total
        return super().count


class ListCacheCountPageNumberPagination(PageNumberPagination):
    """
    ViewSet.list_cache_prefix 가 설정된 경우 count를 Redis에 캐시한다.
    """

    django_paginator_class = CachedCountPaginator

    def paginate_queryset(self, queryset, request, view=None):
        page_size = self.get_page_size(request)
        if not page_size:
            return None

        prefix = getattr(view, "list_cache_prefix", None)
        cached_count = None
        if prefix:
            cached_count = get_or_set_cached_list_count(request, prefix, queryset)

        paginator = self.django_paginator_class(
            queryset,
            page_size,
            cached_count=cached_count,
        )
        page_number = self.get_page_number(request, paginator)

        try:
            self.page = paginator.page(page_number)
        except InvalidPage as exc:
            msg = self.invalid_page_message.format(detail=exc.args[0])
            raise NotFound(msg) from exc

        if paginator.num_pages > 1 and self.template is not None:
            self.display_page_controls = True

        self.request = request
        return list(self.page)


class DashboardPageNumberPagination(ListCacheCountPageNumberPagination):
    """대시보드 목록 (뉴스·소셜)"""

    page_size = 50
    page_size_query_param = "page_size"
    max_page_size = 100


class AnalysisResultPagination(ListCacheCountPageNumberPagination):
    """분석 결과·키워드 등 analyzer 목록"""

    page_size = 20
    page_size_query_param = "page_size"
    max_page_size = 100


class QueryHistoryPagination(ListCacheCountPageNumberPagination):
    """user_qa 히스토리 — settings PAGE_SIZE 와 맞춤"""

    page_size = 100
    page_query_param = "page"
    page_size_query_param = "page_size"
    max_page_size = 200
