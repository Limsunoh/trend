"""
대시보드 API 뷰 모듈

뉴스 기사·소셜 미디어 게시물 목록/상세만 제공합니다.
뉴스 소스·소셜 미디어 소스 → data_collector 앱
분석 결과 → analyzer 앱
"""

from datetime import datetime

from django.db.models import Q, QuerySet
from rest_framework import viewsets
from rest_framework.filters import OrderingFilter, SearchFilter
from rest_framework.pagination import PageNumberPagination

from common.rate_limit import ReadAPIThrottle
from data_collector.models import NewsArticle, SocialMediaPost
from data_collector.serializers import (
    BaseSocialMediaPostSerializer,
    DCInsidePostSerializer,
    NewsArticleSerializer,
    RedditPostSerializer,
)


def filter_queryset_by_params(queryset: QuerySet, request, filters: dict) -> QuerySet:
    """쿼리 파라미터로 쿼리셋 필터링"""
    for param_name, param_type in filters.items():
        value = request.query_params.get(param_name, None)
        if value is not None:
            try:
                if param_type == "bool":
                    value = value.lower() == "true"
                elif param_type == "int":
                    value = int(value)
                queryset = queryset.filter(**{param_name: value})
            except (ValueError, TypeError):
                pass
    return queryset


class DashboardPageNumberPagination(PageNumberPagination):
    """대시보드 목록용 페이지네이션 (한 페이지 50개)"""

    page_size = 50
    page_size_query_param = "page_size"
    max_page_size = 100


# =============================================================================
# 뉴스 기사 / 소셜 미디어 게시물 (목록·상세)
# =============================================================================


class NewsArticleViewSet(viewsets.ReadOnlyModelViewSet):
    """뉴스 기사 ViewSet (읽기 전용)"""

    queryset = NewsArticle.objects.all()
    serializer_class = NewsArticleSerializer
    throttle_classes = [ReadAPIThrottle]
    filter_backends = [SearchFilter, OrderingFilter]
    search_fields = ["title", "description", "author"]
    ordering_fields = ["published_at", "collected_at", "title", "source__publisher"]
    ordering = ["-collected_at"]
    pagination_class = DashboardPageNumberPagination

    def get_queryset(self):
        queryset = NewsArticle.objects.all()
        queryset = filter_queryset_by_params(
            queryset, self.request, {"source": "int", "author": "str"}
        )
        # 드롭다운 검색: search_field + search
        search_field = self.request.query_params.get("search_field")
        search_value = (self.request.query_params.get("search") or "").strip()
        if search_field and search_value:
            if search_field == "category":
                queryset = queryset.filter(category__icontains=search_value)
            elif search_field == "title":
                queryset = queryset.filter(title__icontains=search_value)
            elif search_field == "source":
                # 신문사: publisher, category, url 모두 부분 일치
                queryset = queryset.filter(
                    Q(source__publisher__icontains=search_value)
                    | Q(source__category__icontains=search_value)
                    | Q(source__url__icontains=search_value)
                )
            elif search_field == "published_at":
                try:
                    dt = datetime.strptime(search_value, "%Y-%m-%d").date()
                    queryset = queryset.filter(published_at__date=dt)
                except ValueError:
                    pass
            elif search_field == "collected_at":
                try:
                    dt = datetime.strptime(search_value, "%Y-%m-%d").date()
                    queryset = queryset.filter(collected_at__date=dt)
                except ValueError:
                    pass
        return queryset.select_related("source")


class SocialMediaPostViewSet(viewsets.ReadOnlyModelViewSet):
    """소셜 미디어 게시물 ViewSet (읽기 전용)"""

    queryset = SocialMediaPost.objects.all()
    serializer_class = BaseSocialMediaPostSerializer
    throttle_classes = [ReadAPIThrottle]
    filter_backends = [SearchFilter, OrderingFilter]
    search_fields = ["title", "content", "author"]
    ordering_fields = ["published_at", "collected_at", "title", "source__display_name"]
    ordering = ["-collected_at"]
    pagination_class = DashboardPageNumberPagination

    def get_queryset(self):
        queryset = SocialMediaPost.objects.all()
        queryset = filter_queryset_by_params(
            queryset, self.request, {"source": "int", "is_processed": "bool"}
        )
        platform = self.request.query_params.get("platform")
        if platform:
            queryset = queryset.filter(source__platform=platform)
        # 드롭다운 검색: search_field + search
        search_field = self.request.query_params.get("search_field")
        search_value = (self.request.query_params.get("search") or "").strip()
        if search_field and search_value:
            if search_field == "title":
                queryset = queryset.filter(title__icontains=search_value)
            elif search_field == "source":
                queryset = queryset.filter(
                    Q(source__display_name__icontains=search_value)
                    | Q(source__identifier__icontains=search_value)
                )
            elif search_field == "published_at":
                try:
                    dt = datetime.strptime(search_value, "%Y-%m-%d").date()
                    queryset = queryset.filter(published_at__date=dt)
                except ValueError:
                    pass
            elif search_field == "collected_at":
                try:
                    dt = datetime.strptime(search_value, "%Y-%m-%d").date()
                    queryset = queryset.filter(collected_at__date=dt)
                except ValueError:
                    pass
        return queryset.select_related("source")

    def get_serializer_class(self):
        platform = self.request.query_params.get("platform")
        if hasattr(self, "get_object"):
            try:
                obj = self.get_object()
                if obj and obj.source:
                    platform = obj.source.platform
            except Exception:
                pass
        if platform == "reddit":
            return RedditPostSerializer
        if platform == "dcinside":
            return DCInsidePostSerializer
        return BaseSocialMediaPostSerializer
