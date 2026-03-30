import logging

from rest_framework import status, viewsets
from rest_framework.response import Response

from common.list_cache import get_cached_list_response, set_cached_list_response
from common.pagination import QueryHistoryPagination

from .models import QueryHistory
from .serializers import (
    QueryHistorySerializer,
    QueryRequestSerializer,
    QueryResponseSerializer,
)
from .services import get_rag_service

logger = logging.getLogger(__name__)


class QueryHistoryViewSet(viewsets.ReadOnlyModelViewSet):
    """
    질의응답 히스토리 조회. 목록은 Redis 캐시로 응답 가속.
    """

    list_cache_prefix = "user_qa:history"
    queryset = QueryHistory.objects.all().order_by("-id")
    serializer_class = QueryHistorySerializer
    pagination_class = QueryHistoryPagination

    def list(self, request, *args, **kwargs):
        # 캐시 hit 시 DB/직렬화 없이 바로 반환 (목록 API 부하 감소)
        cached = get_cached_list_response(request, "user_qa:history")
        if cached is not None:
            return Response(cached)
        response = super().list(request, *args, **kwargs)
        set_cached_list_response(request, "user_qa:history", response.data)
        return response


class RAGQueryViewSet(viewsets.ViewSet):
    """
    ✅ RAG + OpenAI LLM 질의응답 엔드포인트
    - POST /api/user_qa/query/
    """

    http_method_names = ["post"]

    def get_serializer_class(self):
        return QueryRequestSerializer

    def create(self, request):
        logger.debug(f"[VIEW] RAGQueryViewSet.create() 호출됨, data={request.data}")

        req = QueryRequestSerializer(data=request.data)
        req.is_valid(raise_exception=True)

        vd = req.validated_data

        query_text = vd["query"]
        top_k = vd["top_k"]
        include_sources = vd["include_sources"]
        use_intent_router = vd.get("use_intent_router", False)

        # ✅ 옵션들 (빈 값은 None 처리)
        model = (vd.get("model") or "").strip() or None
        temperature = vd.get("temperature", None)
        max_output_tokens = vd.get("max_output_tokens", None)
        reasoning_effort = (vd.get("reasoning_effort") or "").strip() or None
        instructions = (vd.get("instructions") or "").strip() or None

        # ✅ 싱글턴으로 RAGService 재사용 (모델/클라이언트 재로딩 방지)
        rag = get_rag_service()

        try:
            result = rag.query(
                query_text=query_text,
                top_k=top_k,
                include_sources=include_sources,
                use_intent_router=use_intent_router,
                model=model,
                temperature=temperature,
                max_output_tokens=max_output_tokens,
                reasoning_effort=reasoning_effort,
                instructions=instructions,
            )
        except Exception as e:
            logger.error(
                f"[VIEW] rag.query() 예외: {type(e).__name__}: {str(e)}", exc_info=True
            )
            raise

        out = QueryResponseSerializer(
            data={
                "query": result.get("query", query_text),
                "answer": result.get("answer", ""),
                "history_id": result.get("history_id"),
                "sources": result.get("sources", []),
                "model": result.get("model", ""),
            }
        )
        out.is_valid(raise_exception=True)

        return Response(out.data, status=status.HTTP_200_OK)


class ConvertToVectorViewSet(viewsets.ViewSet):
    """
    미처리(is_processed=False) 데이터를 소급 임베딩하는 API
    - POST /api/user_qa/convert/
    - 파라미터:
        - type: "all" | "news" | "social" (기본값: "all")
        - collection: Chroma 컬렉션명 (기본값: settings.CHROMA_COLLECTION)
        - limit: 최대 처리 건수 (기본값: 5000)
        - platform: 소셜 플랫폼 필터 (reddit/dcinside, 기본값: None=전체)
    """

    http_method_names = ["post"]

    def create(self, request):
        from .tasks import (
            embed_recent_news_articles_task,
            embed_recent_social_posts_task,
        )

        data_type = (request.data.get("type") or "all").strip()
        collection = request.data.get("collection") or None
        limit = int(request.data.get("limit", 5000))
        platform = request.data.get("platform") or None

        if data_type not in ("all", "news", "social"):
            return Response(
                {
                    "error": f"type은 all/news/social 중 하나여야 합니다. (입력값: {data_type})"
                },
                status=status.HTTP_400_BAD_REQUEST,
            )

        tasks = {}

        if data_type in ("all", "news"):
            task = embed_recent_news_articles_task.delay(
                since=None,
                collection=collection,
                limit=limit,
            )
            tasks["news_task_id"] = task.id
            logger.info(
                f"[ConvertToVector] 뉴스 소급 임베딩 태스크 등록: task_id={task.id}"
            )

        if data_type in ("all", "social"):
            task = embed_recent_social_posts_task.delay(
                since=None,
                collection=collection,
                platform=platform,
                limit=limit,
            )
            tasks["social_task_id"] = task.id
            logger.info(
                f"[ConvertToVector] 소셜 소급 임베딩 태스크 등록: task_id={task.id}"
            )

        return Response(
            {
                "message": "소급 임베딩 태스크가 Celery 큐에 등록되었습니다.",
                "type": data_type,
                "collection": collection,
                "limit": limit,
                "platform": platform,
                "tasks": tasks,
            },
            status=status.HTTP_202_ACCEPTED,
        )
