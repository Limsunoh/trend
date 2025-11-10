from rest_framework import viewsets
from rest_framework.decorators import api_view
from rest_framework.response import Response
from .models import NewsSource, NewsArticle, SocialMediaPost, DataCollectionJob
from .serializers import (
    NewsSourceSerializer,
    NewsArticleSerializer,
    SocialMediaPostSerializer,
    DataCollectionJobSerializer
)


class NewsSourceViewSet(viewsets.ModelViewSet):
    """뉴스 소스 ViewSet"""
    # TODO: queryset, serializer_class 정의
    pass


class NewsArticleViewSet(viewsets.ReadOnlyModelViewSet):
    """뉴스 기사 ViewSet"""
    # TODO: queryset, serializer_class 정의
    pass


class SocialMediaPostViewSet(viewsets.ReadOnlyModelViewSet):
    """소셜 미디어 게시물 ViewSet"""
    # TODO: queryset, serializer_class 정의
    pass


class DataCollectionJobViewSet(viewsets.ReadOnlyModelViewSet):
    """데이터 수집 작업 ViewSet"""
    # TODO: queryset, serializer_class 정의
    pass


@api_view(['POST', 'GET'])
def trigger_collection(request):
    """데이터 수집 작업 트리거"""
    # TODO: 수집 작업 트리거 로직 구현
    return Response({'message': 'Not implemented yet'})
