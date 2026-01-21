from datetime import datetime, time as dt_time
from typing import Optional
from rest_framework import viewsets
from rest_framework.filters import SearchFilter, OrderingFilter
from django.db.models import QuerySet
from django.utils import timezone
from django.utils.dateparse import parse_datetime, parse_date
from drf_spectacular.utils import (
    extend_schema,
    OpenApiParameter,
    OpenApiTypes
)

from data_collector.models import (
    NewsSource,
    NewsArticle,
    SocialMediaSource,
    SocialMediaPost,
)
from data_collector.serializers import (
    NewsSourceSerializer,
    NewsArticleSerializer,
    SocialMediaSourceSerializer,
    BaseSocialMediaPostSerializer,
    RedditPostSerializer,
    DCInsidePostSerializer
)
from analyzer.models import TrendAnalysisResult
from analyzer.serializers import TrendAnalysisResultSerializer


def filter_queryset_by_params(
    queryset: QuerySet,
    request,
    filters: dict
) -> QuerySet:
    """
    쿼리 파라미터로 쿼리셋 필터링 헬퍼 함수

    Args:
        queryset: 필터링할 쿼리셋
        request: 요청 객체
        filters: 필터 설정 딕셔너리
            예: {'is_active': 'bool', 'source_type': 'str'}

    Returns:
        필터링된 쿼리셋
    """
    for param_name, param_type in filters.items():
        value = request.query_params.get(param_name, None)
        if value is not None:
            try:
                if param_type == 'bool':
                    value = value.lower() == 'true'
                elif param_type == 'int':
                    value = int(value)
                queryset = queryset.filter(**{param_name: value})
            except (ValueError, TypeError):
                pass
    return queryset


def _make_aware(value: Optional[datetime]) -> Optional[datetime]:
    """문자열로 들어온 날짜를 현재 타임존 기준 aware datetime으로 변환"""
    if value and timezone.is_naive(value):
        return timezone.make_aware(value, timezone.get_current_timezone())
    return value


# ============================================================================
# Data Collector ViewSets
# ============================================================================

class NewsSourceViewSet(viewsets.ReadOnlyModelViewSet):
    """뉴스 소스 ViewSet (읽기 전용)"""
    queryset = NewsSource.objects.all()
    serializer_class = NewsSourceSerializer
    filter_backends = [SearchFilter, OrderingFilter]
    search_fields = ['publisher', 'category', 'url']
    ordering_fields = [
        'publisher', 'category', 'created_at', 'last_collected_at'
    ]
    ordering = ['-created_at']

    def get_queryset(self):
        queryset = NewsSource.objects.all()
        return filter_queryset_by_params(
            queryset, self.request,
            {'is_active': 'bool', 'source_type': 'str'}
        )


class NewsArticleViewSet(viewsets.ReadOnlyModelViewSet):
    """뉴스 기사 ViewSet (읽기 전용)"""
    queryset = NewsArticle.objects.all()
    serializer_class = NewsArticleSerializer
    filter_backends = [SearchFilter, OrderingFilter]
    search_fields = ['title', 'description', 'author']
    ordering_fields = ['published_at', 'collected_at', 'title']
    ordering = ['-published_at', '-collected_at']

    def get_queryset(self):
        queryset = NewsArticle.objects.all()
        queryset = filter_queryset_by_params(
            queryset, self.request,
            {
                'source': 'int',
                'category': 'str',
                'is_processed': 'bool',
                'title': 'str',
                'author': 'str'
            }
        )
        return queryset.select_related('source')


class SocialMediaPostViewSet(viewsets.ReadOnlyModelViewSet):
    """소셜 미디어 게시물 ViewSet (읽기 전용)"""
    queryset = SocialMediaPost.objects.all()
    serializer_class = BaseSocialMediaPostSerializer  # 기본값
    filter_backends = [SearchFilter, OrderingFilter]
    search_fields = ['title', 'content', 'author']
    ordering_fields = ['published_at', 'collected_at', 'title']
    ordering = ['-published_at', '-collected_at']
    
    def get_queryset(self):
        """쿼리셋 필터링"""
        queryset = SocialMediaPost.objects.all()
        queryset = filter_queryset_by_params(
            queryset, self.request,
            {
                'source': 'int',
                'is_processed': 'bool',
            }
        )
        # 플랫폼별 필터링
        platform = self.request.query_params.get('platform')
        if platform:
            queryset = queryset.filter(source__platform=platform)
        
        return queryset.select_related('source')
    
    def get_serializer_class(self):
        """플랫폼별로 적절한 시리얼라이저 선택"""
        # 쿼리 파라미터에서 플랫폼 확인
        platform = self.request.query_params.get('platform')
        
        # 객체가 있는 경우 (detail view)
        if hasattr(self, 'get_object'):
            try:
                obj = self.get_object()
                if obj and obj.source:
                    platform = obj.source.platform
            except Exception:
                pass
        
        # 플랫폼별 시리얼라이저 선택
        if platform == 'reddit':
            return RedditPostSerializer
        elif platform == 'dcinside':
            return DCInsidePostSerializer
        else:
            # 기본 시리얼라이저 (플랫폼이 명시되지 않은 경우)
            return BaseSocialMediaPostSerializer


class SocialMediaSourceViewSet(viewsets.ModelViewSet):
    """소셜 미디어 소스 ViewSet"""
    queryset = SocialMediaSource.objects.all()
    serializer_class = SocialMediaSourceSerializer
    filter_backends = [SearchFilter, OrderingFilter]
    search_fields = ['display_name', 'identifier', 'url', 'category']
    ordering_fields = [
        'platform', 'display_name', 'created_at', 'last_collected_at'
    ]
    ordering = ['-created_at']

    def get_queryset(self):
        queryset = SocialMediaSource.objects.all()
        return filter_queryset_by_params(
            queryset, self.request,
            {
                'is_active': 'bool',
                'platform': 'str',
                'source_type': 'str'
            }
        )


# ============================================================================
# Analyzer ViewSets
# ============================================================================

_COMMON_LANG_PARAMETER = OpenApiParameter(
    name='lang',
    type=OpenApiTypes.STR,
    description='응답 언어 (ko 또는 en, 기본 ko)',
    required=False
)


class TrendAnalysisResultViewSet(viewsets.ReadOnlyModelViewSet):
    """트렌드 분석 결과 ViewSet (전체 목록 조회용)"""
    # 기본 queryset을 최신 1000개로 제한 (Swagger 스키마 생성 시 성능 향상)
    queryset = TrendAnalysisResult.objects.all()[:1000]
    serializer_class = TrendAnalysisResultSerializer
    # Pagination 명시적 설정 (기본값 사용하지만 명확히)
    pagination_class = None  # REST_FRAMEWORK의 기본 pagination 사용

    def get_queryset(self):
        # 목록 조회 필터: 분석 타입/플랫폼/기간/상태/생성일
        # 실제 조회 시에는 필터링된 전체 결과 반환
        queryset = TrendAnalysisResult.objects.all()
        params = self.request.query_params

        analysis_type = params.get('analysis_type')
        if analysis_type:
            queryset = queryset.filter(analysis_type=analysis_type)

        platform = params.get('platform')
        if platform:
            queryset = queryset.filter(platform=platform)

        days = params.get('days')
        if days:
            try:
                queryset = queryset.filter(days=int(days))
            except ValueError:
                return queryset.none()

        status_param = params.get('status')
        if status_param:
            queryset = queryset.filter(status=status_param)

        created_from = params.get('created_from')
        if created_from:
            dt_from = parse_datetime(created_from)
            if dt_from is None:
                date_from = parse_date(created_from)
                if date_from:
                    dt_from = datetime.combine(date_from, dt_time.min)
            dt_from = _make_aware(dt_from)
            if dt_from:
                queryset = queryset.filter(created_at__gte=dt_from)

        created_to = params.get('created_to')
        if created_to:
            dt_to = parse_datetime(created_to)
            if dt_to is None:
                date_to = parse_date(created_to)
                if date_to:
                    dt_to = datetime.combine(date_to, dt_time.max)
            dt_to = _make_aware(dt_to)
            if dt_to:
                queryset = queryset.filter(created_at__lte=dt_to)

        return queryset


_LIST_ANALYSIS_PARAMETERS = [
    _COMMON_LANG_PARAMETER,
    OpenApiParameter(
        name='platform',
        type=OpenApiTypes.STR,
        description='플랫폼 (news, sns, both)',
        required=False
    ),
    OpenApiParameter(
        name='days',
        type=OpenApiTypes.INT,
        description='분석 기간 일수',
        required=False
    ),
    OpenApiParameter(
        name='status',
        type=OpenApiTypes.STR,
        description='상태 (success, failed)',
        required=False
    ),
]


class BaseAnalysisViewSet(viewsets.ReadOnlyModelViewSet):
    """분석 결과 ViewSet 기본 클래스"""
    # 기본 queryset을 최신 100개로 제한 (Swagger 스키마 생성 시 성능 향상)
    # 실제 조회는 get_queryset()에서 필터링된 전체 결과 반환
    queryset = TrendAnalysisResult.objects.all()[:100]
    serializer_class = TrendAnalysisResultSerializer
    analysis_type = None  # 하위 클래스에서 설정
    # Pagination 명시적 설정
    pagination_class = None  # REST_FRAMEWORK의 기본 pagination 사용

    def _parse_url_params(self):
        """쿼리 파라미터에서 platform과 days 파라미터 파싱"""
        platform = self.request.query_params.get('platform', None)
        days_param = self.request.query_params.get('days')
        days = None
        
        if days_param:
            try:
                days = int(days_param)
            except ValueError:
                pass
        
        return platform, days

    @extend_schema(parameters=_LIST_ANALYSIS_PARAMETERS)
    def list(self, request, *args, **kwargs):
        """분석 결과 목록 조회 (쿼리 파라미터로 필터링)"""
        return super().list(request, *args, **kwargs)

    def get_queryset(self):
        """analysis_type, platform, days로 필터링된 쿼리셋 반환"""
        # 실제 조회 시에는 필터링된 전체 결과 반환 (기본 queryset 제한 무시)
        queryset = TrendAnalysisResult.objects.all()
        if self.analysis_type:
            queryset = queryset.filter(analysis_type=self.analysis_type)
        
        platform, days = self._parse_url_params()
        if platform:
            queryset = queryset.filter(platform=platform)
        if days is not None:
            queryset = queryset.filter(days=days)
        
        # status 필터링도 추가
        status_param = self.request.query_params.get('status')
        if status_param:
            queryset = queryset.filter(status=status_param)
        
        return queryset


# 각 분석 타입별 ViewSet
class KeywordsAnalysisViewSet(BaseAnalysisViewSet):
    """키워드 분석 결과 ViewSet"""
    analysis_type = 'keywords'


class ComparePlatformsAnalysisViewSet(BaseAnalysisViewSet):
    """플랫폼 비교 분석 결과 ViewSet"""
    analysis_type = 'compare_platforms'


class HotKeywordsAnalysisViewSet(BaseAnalysisViewSet):
    """인기 키워드 분석 결과 ViewSet"""
    analysis_type = 'hot_keywords'


class TimeLagAnalysisViewSet(BaseAnalysisViewSet):
    """시간차 분석 결과 ViewSet"""
    analysis_type = 'time_lag'


class SurgeKeywordsAnalysisViewSet(BaseAnalysisViewSet):
    """급상승 키워드 분석 결과 ViewSet"""
    analysis_type = 'surge_keywords'


class TrendSynchronizationAnalysisViewSet(BaseAnalysisViewSet):
    """트렌드 동기화 분석 결과 ViewSet"""
    analysis_type = 'trend_synchronization'


class HourlyTrendsAnalysisViewSet(BaseAnalysisViewSet):
    """시간대별 트렌드 분석 결과 ViewSet"""
    analysis_type = 'hourly_trends'


class KeywordOccurrenceTimesAnalysisViewSet(BaseAnalysisViewSet):
    """키워드 등장 시간 분석 결과 ViewSet"""
    analysis_type = 'keyword_occurrence_times'


class KeywordTimelineAnalysisViewSet(BaseAnalysisViewSet):
    """키워드 타임라인 분석 결과 ViewSet"""
    analysis_type = 'keyword_timeline'


class MultipleKeywordsTimelineAnalysisViewSet(BaseAnalysisViewSet):
    """다중 키워드 타임라인 분석 결과 ViewSet"""
    analysis_type = 'multiple_keywords_timeline'


class EngagementKeywordsAnalysisViewSet(BaseAnalysisViewSet):
    """참여도 기반 키워드 분석 결과 ViewSet"""
    analysis_type = 'engagement_keywords'
