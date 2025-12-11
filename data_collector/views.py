"""
데이터 수집 API 뷰 모듈
"""
import logging
from rest_framework import viewsets, status
from rest_framework.response import Response
from rest_framework.filters import SearchFilter, OrderingFilter
from django.db.models import QuerySet
from .models import (
    NewsSource,
    NewsArticle,
    SocialMediaSource,
    SocialMediaPost,
    DataCollectionJob
)
from .serializers import (
    NewsSourceSerializer,
    NewsArticleSerializer,
    SocialMediaSourceSerializer,
    BaseSocialMediaPostSerializer,
    RedditPostSerializer,
    DCInsidePostSerializer,
    DataCollectionJobSerializer
)
from .tasks import (
    collect_all_rss_news_task,
    collect_all_social_media_task
)
from .services import RSSCollectorService, NewsSourceCSVService

logger = logging.getLogger(__name__)


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


class NewsSourceCreateCSVViewSet(viewsets.ViewSet):
    """CSV 파일에서 NewsSource를 일괄 생성하는 ViewSet"""

    def create(self, request):
        """
        CSV 파일에서 NewsSource를 일괄 생성

        요청 파라미터:
            - csv_file: CSV 파일 경로 (선택, 없으면 기본 경로 사용)
        """
        csv_file = (
            request.data.get('csv_file') or
            request.query_params.get('csv_file')
        )

        # CSV 서비스를 통한 소스 로드
        csv_service = NewsSourceCSVService()
        results = csv_service.load_sources_from_csv(csv_file)

        # 응답 생성
        has_errors_only = (
            results['errors'] > 0 and
            results['created'] == 0 and
            results['updated'] == 0
        )
        if has_errors_only:
            return Response({
                'status': 'error',
                'message': 'CSV 파일 처리 중 오류 발생',
                'results': results
            }, status=status.HTTP_400_BAD_REQUEST)

        message = (
            f'CSV 파일에서 {results["created"]}개 소스 생성, '
            f'{results["updated"]}개 업데이트'
        )

        return Response({
            'status': 'completed',
            'message': message,
            'results': results
        }, status=status.HTTP_201_CREATED)


class NewsSourceCreateViewSet(viewsets.ViewSet):
    """RSS URL로부터 NewsSource 자동 생성 ViewSet"""

    def create(self, request):
        """RSS URL로부터 NewsSource 자동 생성"""
        rss_url = (
            request.data.get('rss_url') or
            request.query_params.get('rss_url')
        )

        if not rss_url:
            return Response({
                'status': 'error',
                'message': 'rss_url 파라미터가 필요합니다.'
            }, status=status.HTTP_400_BAD_REQUEST)

        # 서비스를 통한 RSS 소스 생성
        collector = RSSCollectorService()
        source, result_status, result_dict = collector.create_source_from_rss(
            rss_url=rss_url,
            name=request.data.get('name') or request.query_params.get('name'),
            is_active=request.data.get('is_active', True),
            collection_interval=int(
                request.data.get('collection_interval', 60)
            )
        )

        # 응답 상태 코드 결정
        if result_status == 'created':
            status_code = status.HTTP_201_CREATED
        elif result_status == 'exists':
            status_code = status.HTTP_200_OK
        else:
            status_code = status.HTTP_400_BAD_REQUEST

        return Response({
            'status': result_status,
            'message': result_dict.get('message'),
            'source': NewsSourceSerializer(source).data if source else None
        }, status=status_code)


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


class DataCollectionJobViewSet(viewsets.ReadOnlyModelViewSet):
    """데이터 수집 작업 로그 ViewSet (읽기 전용)"""
    queryset = DataCollectionJob.objects.all()
    serializer_class = DataCollectionJobSerializer
    filter_backends = [OrderingFilter]
    ordering_fields = ['started_at', 'completed_at', 'items_collected']
    ordering = ['-started_at']

    def get_queryset(self):
        queryset = DataCollectionJob.objects.all()
        queryset = filter_queryset_by_params(
            queryset, self.request,
            {'source': 'int', 'status': 'str'}
        )
        return queryset.select_related('source')


class NewsArticleCollectionViewSet(viewsets.ViewSet):
    """뉴스 기사 수집 작업 트리거 ViewSet"""

    def list(self, request):
        """최근 수집 작업 목록 조회 (GET /api/collector/trigger/)"""
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

    def create(self, request):
        """
        모든 활성화된 뉴스 소스에서 수집 작업 시작
        
        이 엔드포인트는 전체 수집만 담당합니다.
        """
        try:
            # 전체 뉴스 소스 수집
            task_result = collect_all_rss_news_task.delay()
            logger.info(
                f"전체 뉴스 소스 수집 태스크 시작 "
                f"(Task ID: {task_result.id})"
            )
            return Response({
                'status': 'started',
                'task_id': task_result.id,
                'message': (
                    '모든 활성화된 뉴스 소스에서 '
                    '수집 작업이 시작되었습니다.'
                )
            }, status=status.HTTP_202_ACCEPTED)

        except Exception as e:
            logger.error(
                f"뉴스 수집 작업 트리거 실패: {str(e)}",
                exc_info=True
            )
            return Response({
                'status': 'error',
                'message': f'수집 작업 시작 실패: {str(e)}'
            }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)


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


class SocialMediaCollectionViewSet(viewsets.ViewSet):
    """소셜 미디어 수집 작업 트리거 ViewSet"""

    def list(self, request):
        """최근 소셜 미디어 수집 작업 목록 조회"""
        recent_sources = (
            SocialMediaSource.objects
            .filter(is_active=True)
            .order_by('-last_collected_at')[:10]
        )
        return Response({
            'message': '활성화된 소셜 미디어 소스 목록',
            'count': len(recent_sources),
            'sources': SocialMediaSourceSerializer(
                recent_sources, many=True
            ).data
        })

    def create(self, request):
        """
        모든 활성화된 소셜 미디어 소스에서 수집 작업 시작
        
        이 엔드포인트는 전체 수집만 담당합니다.
        """
        try:
            # 전체 소셜 미디어 소스 수집
            task_result = collect_all_social_media_task.delay()
            logger.info(
                f"전체 소셜 미디어 소스 수집 태스크 시작 "
                f"(Task ID: {task_result.id})"
            )
            return Response({
                'status': 'started',
                'task_id': task_result.id,
                'message': (
                    '모든 활성화된 소셜 미디어 소스에서 '
                    '수집 작업이 시작되었습니다.'
                )
            }, status=status.HTTP_202_ACCEPTED)

        except Exception as e:
            logger.error(
                f"소셜 미디어 수집 작업 트리거 실패: {str(e)}",
                exc_info=True
            )
            return Response({
                'status': 'error',
                'message': f'수집 작업 시작 실패: {str(e)}'
            }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)


class AllCollectionViewSet(viewsets.ViewSet):
    """News와 Social Media 전체 수집 작업 트리거 ViewSet"""

    def list(self, request):
        """최근 수집 작업 목록 조회"""
        recent_jobs = (
            DataCollectionJob.objects
            .select_related('source')
            .order_by('-started_at')[:10]
        )
        recent_sources = (
            SocialMediaSource.objects
            .filter(is_active=True)
            .order_by('-last_collected_at')[:10]
        )
        return Response({
            'message': '최근 수집 작업 및 소스 목록',
            'news_jobs': {
                'count': len(recent_jobs),
                'jobs': DataCollectionJobSerializer(
                    recent_jobs, many=True
                ).data
            },
            'social_media_sources': {
                'count': len(recent_sources),
                'sources': SocialMediaSourceSerializer(
                    recent_sources, many=True
                ).data
            }
        })

    def create(self, request):
        """
        모든 활성화된 News와 Social Media 소스에서 수집 작업 시작
        
        News와 Social Media 수집을 동시에 시작합니다.
        """
        try:
            # News 전체 수집
            news_task_result = collect_all_rss_news_task.delay()
            
            # Social Media 전체 수집
            social_task_result = collect_all_social_media_task.delay()
            
            logger.info(
                f"전체 수집 태스크 시작 - "
                f"News Task ID: {news_task_result.id}, "
                f"Social Media Task ID: {social_task_result.id}"
            )
            
            return Response({
                'status': 'started',
                'tasks': {
                    'news': {
                        'task_id': news_task_result.id,
                        'message': '뉴스 수집 작업이 시작되었습니다.'
                    },
                    'social_media': {
                        'task_id': social_task_result.id,
                        'message': '소셜 미디어 수집 작업이 시작되었습니다.'
                    }
                },
                'message': (
                    '모든 활성화된 News와 Social Media 소스에서 '
                    '수집 작업이 시작되었습니다.'
                )
            }, status=status.HTTP_202_ACCEPTED)

        except Exception as e:
            logger.error(
                f"전체 수집 작업 트리거 실패: {str(e)}",
                exc_info=True
            )
            return Response({
                'status': 'error',
                'message': f'수집 작업 시작 실패: {str(e)}'
            }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)
