from rest_framework import viewsets
from rest_framework.decorators import api_view
from rest_framework.response import Response
from .models import VectorDocument, QueryHistory
from .serializers import (
    VectorDocumentSerializer,
    QueryHistorySerializer,
    QueryRequestSerializer
)
from .services import VectorDBService, RAGService


class VectorDocumentViewSet(viewsets.ReadOnlyModelViewSet):
    """벡터 문서 ViewSet"""
    # TODO: queryset, serializer_class 정의
    pass


class QueryHistoryViewSet(viewsets.ReadOnlyModelViewSet):
    """질의응답 히스토리 ViewSet"""
    # TODO: queryset, serializer_class 정의
    pass


@api_view(['POST'])
def query(request):
    """RAG 질의응답"""
    # TODO: RAG 질의응답 로직 구현
    return Response({'message': 'Not implemented yet'})


@api_view(['POST'])
def convert_to_vector(request):
    """수집된 데이터를 벡터로 변환"""
    # TODO: 벡터 변환 작업 트리거 로직 구현
    return Response({'message': 'Not implemented yet'})

