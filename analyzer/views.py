from datetime import datetime, time as dt_time
from typing import Optional

from django.utils import timezone
from django.utils.dateparse import parse_datetime, parse_date
from rest_framework import status, viewsets
from rest_framework.decorators import action
from rest_framework.response import Response
from drf_spectacular.utils import (
    extend_schema,
    extend_schema_view,
    OpenApiParameter,
    OpenApiTypes
)

from analyzer.result_storage import cache_latest_analysis
from common.redis_services import AnalysisCacheService
from .models import TrendAnalysisResult
from .serializers import TrendAnalysisResultSerializer


def _make_aware(value: Optional[datetime]) -> Optional[datetime]:
    # 문자열로 들어온 날짜를 현재 타임존 기준 aware datetime으로 변환
    if value and timezone.is_naive(value):
        return timezone.make_aware(value, timezone.get_current_timezone())
    return value


_COMMON_LANG_PARAMETER = OpenApiParameter(
    name='lang',
    type=OpenApiTypes.STR,
    description='응답 언어 (ko 또는 en, 기본 ko)',
    required=False
)

_LIST_PARAMETERS = [
    _COMMON_LANG_PARAMETER,
    OpenApiParameter(
        name='analysis_type',
        type=OpenApiTypes.STR,
        description='분석 타입 (keywords, topics, time_lag 등)',
        required=False
    ),
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
    OpenApiParameter(
        name='created_from',
        type=OpenApiTypes.DATETIME,
        description='시작 시간 (YYYY-MM-DD 또는 ISO)',
        required=False
    ),
    OpenApiParameter(
        name='created_to',
        type=OpenApiTypes.DATETIME,
        description='종료 시간 (YYYY-MM-DD 또는 ISO)',
        required=False
    )
]

_LATEST_PARAMETERS = [
    _COMMON_LANG_PARAMETER,
    OpenApiParameter(
        name='analysis_type',
        type=OpenApiTypes.STR,
        description='분석 타입 (필수)',
        required=True
    ),
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
    )
]


@extend_schema_view(
    list=extend_schema(parameters=_LIST_PARAMETERS),
    latest=extend_schema(parameters=_LATEST_PARAMETERS)
)
class TrendAnalysisResultViewSet(viewsets.ReadOnlyModelViewSet):
    """트렌드 분석 결과 ViewSet"""
    queryset = TrendAnalysisResult.objects.all()
    serializer_class = TrendAnalysisResultSerializer

    def get_queryset(self):
        # 목록 조회 필터: 분석 타입/플랫폼/기간/상태/생성일
        queryset = super().get_queryset()
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

    @action(detail=False, methods=['get'], url_path='latest')
    def latest(self, request):
        # 최신 분석 결과: Redis 캐시 우선 조회 후 DB fallback
        lang = request.query_params.get('lang', 'ko')
        analysis_type = request.query_params.get('analysis_type')
        if not analysis_type:
            return Response(
                {"detail": "analysis_type is required"},
                status=status.HTTP_400_BAD_REQUEST
            )

        platform = request.query_params.get('platform')
        days = request.query_params.get('days')
        if days is not None:
            try:
                days = int(days)
            except ValueError:
                return Response(
                    {"detail": "days must be an integer"},
                    status=status.HTTP_400_BAD_REQUEST
                )

        extra_params = {
            key: value for key, value in request.query_params.items()
            if key not in {'analysis_type', 'platform', 'days'}
        }
        parameters = extra_params or None

        cache_service = AnalysisCacheService()
        cached = cache_service.get_latest_result(
            analysis_type=analysis_type,
            platform=platform,
            days=days,
            parameters=parameters
        )
        if cached is not None:
            # 캐시에 있으면 바로 반환 (응답 키 변환은 serializer로 처리)
            payload = {
                "analysis_type": analysis_type,
                "platform": platform,
                "days": days,
                "parameters": parameters or {},
                "cached": True,
                "result_data": cached
            }
            payload = TrendAnalysisResultSerializer.translate_latest_payload(
                payload,
                lang
            )
            return Response(payload)

        queryset = TrendAnalysisResult.objects.filter(
            analysis_type=analysis_type
        )
        if platform is not None:
            queryset = queryset.filter(platform=platform)
        if days is not None:
            queryset = queryset.filter(days=days)

        latest_result = queryset.order_by('-created_at').first()
        if not latest_result:
            return Response(
                {"detail": "result not found"},
                status=status.HTTP_404_NOT_FOUND
            )

        # DB에서 가져온 최신 결과를 다시 캐시에 저장
        cache_latest_analysis(
            analysis_type=analysis_type,
            result=latest_result.result_data,
            parameters=parameters,
            platform=platform,
            days=days
        )
        data = self.get_serializer(latest_result).data
        data["cached"] = False
        return Response(data)
