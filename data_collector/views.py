"""
데이터 수집 API 뷰 모듈
"""
import logging
from rest_framework import viewsets, status
from rest_framework.decorators import api_view, action
from rest_framework.response import Response
from rest_framework.filters import SearchFilter, OrderingFilter
from django.db.models import QuerySet
from .models import NewsSource, NewsArticle, SocialMediaPost, DataCollectionJob
from .serializers import (
    NewsSourceSerializer,
    NewsArticleSerializer,
    SocialMediaPostSerializer,
    DataCollectionJobSerializer
)
from .tasks import collect_rss_news_task, collect_all_rss_news_task

logger = logging.getLogger(__name__)


def filter_queryset_by_params(
    queryset: QuerySet, request, filters: dict
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


class NewsSourceViewSet(viewsets.ModelViewSet):
    """뉴스 소스 ViewSet"""
    queryset = NewsSource.objects.all()
    serializer_class = NewsSourceSerializer
    filter_backends = [SearchFilter, OrderingFilter]
    search_fields = ['name', 'url']
    ordering_fields = ['name', 'created_at', 'last_collected_at']
    ordering = ['-created_at']

    def get_queryset(self):
        queryset = super().get_queryset()
        return filter_queryset_by_params(
            queryset, self.request,
            {'is_active': 'bool', 'source_type': 'str'}
        )
    
    @action(detail=True, methods=['post'])
    def collect(self, request, pk=None):
        """특정 소스에서 데이터 수집 시작"""
        source = self.get_object()
        try:
            task_result = collect_rss_news_task.delay(source_id=source.id)
            logger.info(
                f"소스 수집 태스크 시작: {source.name} "
                f"(ID: {source.id}, Task ID: {task_result.id})"
            )
            return Response({
                'status': 'started',
                'task_id': task_result.id,
                'message': f'{source.name}에서 수집 작업이 시작되었습니다.',
                'source': source.name,
                'source_id': source.id
            }, status=status.HTTP_202_ACCEPTED)
        except Exception as e:
            logger.error(
                f"소스 수집 태스크 시작 실패: {source.name} - {str(e)}",
                exc_info=True
            )
            return Response({
                'status': 'error',
                'message': f'수집 작업 시작 실패: {str(e)}',
                'source': source.name
            }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

    @action(detail=True, methods=['get'])
    def articles(self, request, pk=None):
        """특정 소스의 기사 목록 조회"""
        source = self.get_object()
        limit = int(request.query_params.get('limit', 20))
        offset = int(request.query_params.get('offset', 0))
        ordering = request.query_params.get('ordering', '-published_at')
        
        articles = NewsArticle.objects.filter(
            source=source
        ).order_by(ordering)
        total_count = articles.count()
        articles = articles[offset:offset + limit]

        return Response({
            'source': source.name,
            'source_id': source.id,
            'total_count': total_count,
            'limit': limit,
            'offset': offset,
            'articles': NewsArticleSerializer(articles, many=True).data
        })


class NewsArticleViewSet(viewsets.ReadOnlyModelViewSet):
    """뉴스 기사 ViewSet (읽기 전용)"""
    queryset = NewsArticle.objects.all()
    serializer_class = NewsArticleSerializer
    filter_backends = [SearchFilter, OrderingFilter]
    search_fields = ['title', 'description', 'author']
    ordering_fields = ['published_at', 'collected_at', 'title']
    ordering = ['-published_at', '-collected_at']

    def get_queryset(self):
        queryset = super().get_queryset()
        # source 필터링 (int 타입)
        source_id = self.request.query_params.get('source', None)
        if source_id:
            try:
                queryset = queryset.filter(source_id=int(source_id))
            except ValueError:
                pass
        # 나머지 필터링
        queryset = filter_queryset_by_params(
            queryset, self.request,
            {'category': 'str', 'is_processed': 'bool'}
        )
        return queryset.select_related('source')


class SocialMediaPostViewSet(viewsets.ReadOnlyModelViewSet):
    """소셜 미디어 게시물 ViewSet (읽기 전용, TODO)"""
    queryset = SocialMediaPost.objects.all()
    serializer_class = SocialMediaPostSerializer


class DataCollectionJobViewSet(viewsets.ReadOnlyModelViewSet):
    """데이터 수집 작업 로그 ViewSet (읽기 전용)"""
    queryset = DataCollectionJob.objects.all()
    serializer_class = DataCollectionJobSerializer
    filter_backends = [OrderingFilter]
    ordering_fields = ['started_at', 'completed_at', 'items_collected']
    ordering = ['-started_at']

    def get_queryset(self):
        queryset = super().get_queryset()
        # source 필터링 (int 타입)
        source_id = self.request.query_params.get('source', None)
        if source_id:
            try:
                queryset = queryset.filter(source_id=int(source_id))
            except ValueError:
                pass
        # status 필터링
        queryset = filter_queryset_by_params(
            queryset, self.request, {'status': 'str'}
        )
        return queryset.select_related('source')


@api_view(['POST', 'GET'])
def trigger_collection(request):
    """데이터 수집 작업 트리거 API"""
    if request.method == 'GET':
        recent_jobs = (
            DataCollectionJob.objects
            .select_related('source')
            .order_by('-started_at')[:10]
        )
        return Response({
            'message': '최근 수집 작업 목록',
            'count': len(recent_jobs),
            'jobs': DataCollectionJobSerializer(recent_jobs, many=True).data
        })

    try:
        source_id = (
            request.data.get('source_id') or
            request.query_params.get('source_id')
        )
        source_id = int(source_id) if source_id else None
        source_name = (
            request.data.get('source_name') or
            request.query_params.get('source_name')
        )
        source_name = source_name.strip() if source_name else None
        collect_all = (
            request.data.get('collect_all') or
            request.query_params.get('collect_all')
        )
        collect_all = (
            str(collect_all).lower() == 'true' if collect_all else False
        )

        if collect_all or (not source_id and not source_name):
            task_result = collect_all_rss_news_task.delay()
            logger.info(f"전체 소스 수집 태스크 시작 (Task ID: {task_result.id})")
            return Response({
                'status': 'started',
                'task_id': task_result.id,
                'message': '모든 활성화된 소스에서 수집 작업이 시작되었습니다.',
                'collect_all': True
            }, status=status.HTTP_202_ACCEPTED)

        task_result = collect_rss_news_task.delay(
            source_id=source_id, source_name=source_name
        )
        logger.info(
            f"소스 수집 태스크 시작: source_id={source_id}, "
            f"source_name={source_name} (Task ID: {task_result.id})"
        )
        return Response({
            'status': 'started',
            'task_id': task_result.id,
            'message': '수집 작업이 시작되었습니다.',
            'source_id': source_id,
            'source_name': source_name
        }, status=status.HTTP_202_ACCEPTED)

    except ValueError as e:
        logger.error(f"수집 작업 트리거 실패: 잘못된 파라미터 - {str(e)}")
        return Response({
            'status': 'error',
            'message': f'잘못된 파라미터: {str(e)}'
        }, status=status.HTTP_400_BAD_REQUEST)
    except Exception as e:
        logger.error(f"수집 작업 트리거 실패: {str(e)}", exc_info=True)
        return Response({
            'status': 'error',
            'message': f'수집 작업 시작 실패: {str(e)}'
        }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)
