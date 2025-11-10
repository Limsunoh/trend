from rest_framework import viewsets
from rest_framework.decorators import api_view
from rest_framework.response import Response
from .models import Keyword, Topic, TrendAnalysis, HotKeyword
from .serializers import (
    KeywordSerializer,
    TopicSerializer,
    TrendAnalysisSerializer,
    HotKeywordSerializer
)


class KeywordViewSet(viewsets.ReadOnlyModelViewSet):
    """키워드 ViewSet"""
    # TODO: queryset, serializer_class 정의
    pass


class TopicViewSet(viewsets.ReadOnlyModelViewSet):
    """토픽 ViewSet"""
    # TODO: queryset, serializer_class 정의
    pass


class TrendAnalysisViewSet(viewsets.ReadOnlyModelViewSet):
    """트렌드 분석 ViewSet"""
    # TODO: queryset, serializer_class 정의
    pass


class HotKeywordViewSet(viewsets.ReadOnlyModelViewSet):
    """인기 키워드 ViewSet"""
    # TODO: queryset, serializer_class 정의
    pass


@api_view(['POST'])
def analyze_trends(request):
    """트렌드 분석 작업 트리거"""
    # TODO: 분석 작업 트리거 로직 구현
    return Response({'message': 'Not implemented yet'})
