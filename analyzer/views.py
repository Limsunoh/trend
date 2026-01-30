"""
분석 결과 API 뷰 모듈
"""
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

from analyzer.models import TrendAnalysisResult
from analyzer.serializers import TrendAnalysisResultSerializer


def _make_aware(value: Optional[datetime]) -> Optional[datetime]:
    """문자열로 들어온 날짜를 현재 타임존 기준 aware datetime으로 변환"""
    if value and timezone.is_naive(value):
        return timezone.make_aware(value, timezone.get_current_timezone())
    return value


_COMMON_LANG_PARAMETER = OpenApiParameter(
    name='lang',
    type=OpenApiTypes.STR,
    description='응답 언어 (ko 또는 en, 기본 ko)',
    required=False
)

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


class TrendAnalysisResultViewSet(viewsets.ReadOnlyModelViewSet):
    """트렌드 분석 결과 ViewSet (전체 목록 조회용)"""
    queryset = TrendAnalysisResult.objects.all()[:1000]
    serializer_class = TrendAnalysisResultSerializer
    pagination_class = None

    def get_queryset(self):
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


class BaseAnalysisViewSet(viewsets.ReadOnlyModelViewSet):
    """분석 결과 ViewSet 기본 클래스"""
    queryset = TrendAnalysisResult.objects.all()[:100]
    serializer_class = TrendAnalysisResultSerializer
    analysis_type = None
    pagination_class = None

    def _parse_url_params(self):
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
        return super().list(request, *args, **kwargs)

    def get_queryset(self):
        queryset = TrendAnalysisResult.objects.all()
        if self.analysis_type:
            queryset = queryset.filter(analysis_type=self.analysis_type)
        platform, days = self._parse_url_params()
        if platform:
            queryset = queryset.filter(platform=platform)
        if days is not None:
            queryset = queryset.filter(days=days)
        status_param = self.request.query_params.get('status')
        if status_param:
            queryset = queryset.filter(status=status_param)
        return queryset


class KeywordsAnalysisViewSet(BaseAnalysisViewSet):
    analysis_type = 'keywords'


class ComparePlatformsAnalysisViewSet(BaseAnalysisViewSet):
    analysis_type = 'compare_platforms'


class HotKeywordsAnalysisViewSet(BaseAnalysisViewSet):
    analysis_type = 'hot_keywords'


class TimeLagAnalysisViewSet(BaseAnalysisViewSet):
    analysis_type = 'time_lag'


class SurgeKeywordsAnalysisViewSet(BaseAnalysisViewSet):
    analysis_type = 'surge_keywords'


class TrendSynchronizationAnalysisViewSet(BaseAnalysisViewSet):
    analysis_type = 'trend_synchronization'


class HourlyTrendsAnalysisViewSet(BaseAnalysisViewSet):
    analysis_type = 'hourly_trends'


class KeywordOccurrenceTimesAnalysisViewSet(BaseAnalysisViewSet):
    analysis_type = 'keyword_occurrence_times'


class KeywordTimelineAnalysisViewSet(BaseAnalysisViewSet):
    analysis_type = 'keyword_timeline'


class MultipleKeywordsTimelineAnalysisViewSet(BaseAnalysisViewSet):
    analysis_type = 'multiple_keywords_timeline'


class EngagementKeywordsAnalysisViewSet(BaseAnalysisViewSet):
    analysis_type = 'engagement_keywords'
