from rest_framework import viewsets
from rest_framework.decorators import api_view
from rest_framework.response import Response

from .services import RAGService

# TODO: QueryHistory, VectorDocument, serializers 사용


class VectorDocumentViewSet(viewsets.ReadOnlyModelViewSet):
    """벡터 문서 ViewSet"""

    # TODO: queryset, serializer_class 정의
    pass


class QueryHistoryViewSet(viewsets.ReadOnlyModelViewSet):
    """질의응답 히스토리 ViewSet"""

    # TODO: queryset, serializer_class 정의
    pass


@api_view(["POST"])
def query(request):
    """
    RAG 질의응답
    - 우선순위 1: RAG 질의응답 캐싱 (RAGService 내부에서 처리)
    """
    rag_service = RAGService()

    # TODO: 요청 데이터 검증
    query_text = request.data.get("query", "")
    top_k = request.data.get("top_k", 5)
    include_sources = request.data.get("include_sources", True)

    # RAG 서비스 호출 (내부에서 캐싱 처리)
    result = rag_service.query(
        query_text=query_text, top_k=top_k, include_sources=include_sources
    )

    # TODO: QueryHistory에 저장
    # QueryHistory.objects.create(...)

    return Response(result)


@api_view(["POST"])
def convert_to_vector(request):
    """수집된 데이터를 벡터로 변환"""
    # TODO: 벡터 변환 작업 트리거 로직 구현
    return Response({"message": "Not implemented yet"})
