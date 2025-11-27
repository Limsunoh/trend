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
    """
    데이터 수집 작업 트리거 API 엔드포인트
    
    경향신문 RSS 피드 수집 작업을 수동으로 트리거합니다.
    Celery 태스크를 비동기로 실행하여 즉시 응답을 반환합니다.
    
    HTTP 메서드:
        - GET: 수집 작업 상태 확인
        - POST: 수집 작업 시작
    
    요청 파라미터 (POST):
        - source_id (선택): 특정 뉴스 소스 ID. 없으면 경향신문 소스를 자동으로 찾거나 생성합니다.
        
    응답 형식:
        {
            'status': 'started' | 'error',
            'task_id': 'celery-task-id',
            'message': '작업이 시작되었습니다.'
        }
        
    사용 예시:
        # 모든 활성화된 소스 수집
        POST /api/collect/trigger/
        
        # 특정 소스 수집
        POST /api/collect/trigger/?source_id=1
    """
    from .tasks import collect_rss_news_task
    
    if request.method == 'GET':
        # GET 요청: 최근 수집 작업 상태 조회
        recent_jobs = DataCollectionJob.objects.order_by('-started_at')[:10]
        
        return Response({
            'message': '최근 수집 작업 목록',
            'jobs': [
                {
                    'id': job.id,
                    'source': job.source.name if job.source else None,
                    'status': job.status,
                    'started_at': job.started_at,
                    'completed_at': job.completed_at,
                    'items_collected': job.items_collected,
                }
                for job in recent_jobs
            ]
        })
    
    # POST 요청: 수집 작업 시작
    try:
        # source_id 파라미터 추출 (선택적)
        source_id = request.data.get('source_id') or request.query_params.get('source_id')
        source_id = int(source_id) if source_id else None
        
        # Celery 태스크 비동기 실행
        # delay() 메서드를 사용하여 태스크를 큐에 추가합니다.
        # 즉시 응답을 반환하고 백그라운드에서 작업이 실행됩니다.
        task_result = collect_rss_news_task.delay(source_id=source_id)
        
        return Response({
            'status': 'started',
            'task_id': task_result.id,  # Celery 태스크 ID
            'message': '수집 작업이 시작되었습니다.',
            'source_id': source_id,
        }, status=202)  # 202 Accepted: 요청이 수락되었지만 아직 처리 중
        
    except Exception as e:
        # 오류 발생 시
        import logging
        logger = logging.getLogger(__name__)
        logger.error(f"수집 작업 트리거 실패: {str(e)}", exc_info=True)
        
        return Response({
            'status': 'error',
            'message': f'수집 작업 시작 실패: {str(e)}'
        }, status=500)
