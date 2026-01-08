"""
데이터 수집 API 뷰 모듈
"""
import logging
from rest_framework import viewsets, status
from rest_framework.response import Response
from rest_framework.views import APIView
from rest_framework.permissions import AllowAny
from rest_framework.filters import SearchFilter, OrderingFilter
from django.db.models import QuerySet
from django.http import HttpResponse
from django.shortcuts import redirect
from django.utils import timezone
from urllib.parse import unquote
import requests
from datetime import timedelta
from .models import (
    NewsSource,
    NewsArticle,
    SocialMediaSource,
    SocialMediaPost,
    DataCollectionJob,
    CollectionSession
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


class ThumbnailProxyView(APIView):
    """
    썸네일 이미지 프록시 뷰
    
    DC Inside 등 Referer 헤더가 필요한 이미지를 프록시를 통해 제공합니다.
    Reddit 이미지는 그대로 리다이렉트합니다.
    """
    permission_classes = [AllowAny]  # 인증 없이 접근 가능
    
    def get(self, request):
        """
        썸네일 이미지 프록시
        
        Query Parameters:
            url: 프록시할 이미지 URL (필수)
        """
        image_url = request.query_params.get('url')
        
        if not image_url:
            return Response(
                {'error': 'url 파라미터가 필요합니다.'},
                status=status.HTTP_400_BAD_REQUEST
            )
        
        try:
            # URL 디코딩
            image_url = unquote(image_url)
            
            # Reddit 이미지는 그대로 리다이렉트 (이미 접근 가능)
            if 'reddit' in image_url.lower() or 'redd.it' in image_url.lower():
                return redirect(image_url)
            
            # DC Inside 등 Referer가 필요한 이미지는 프록시
            headers = {
                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
                'Referer': 'https://gall.dcinside.com/',
            }
            
            # 이미지 다운로드
            response = requests.get(image_url, headers=headers, timeout=10, stream=True)
            response.raise_for_status()
            
            # 이미지 데이터 가져오기
            image_data = response.content
            
            # Content-Type 확인 (실제 이미지 데이터의 매직 넘버로 감지)
            content_type = response.headers.get('Content-Type', '')
            
            # Content-Type이 application/octet-stream이거나 이미지가 아닌 경우,
            # 실제 이미지 데이터의 매직 넘버로 감지
            if (not content_type or 
                content_type.startswith('application/octet-stream') or
                not content_type.startswith('image/')):
                
                # 이미지 파일 시그니처(매직 넘버)로 감지
                if len(image_data) >= 4:
                    # JPEG: FF D8 FF
                    if image_data[:3] == b'\xff\xd8\xff':
                        content_type = 'image/jpeg'
                    # PNG: 89 50 4E 47
                    elif image_data[:4] == b'\x89PNG':
                        content_type = 'image/png'
                    # GIF: 47 49 46 38 (GIF8)
                    elif image_data[:4] == b'GIF8':
                        content_type = 'image/gif'
                    # WebP: 52 49 46 46 ... 57 45 42 50 (RIFF...WEBP)
                    elif len(image_data) >= 12 and image_data[:4] == b'RIFF' and image_data[8:12] == b'WEBP':
                        content_type = 'image/webp'
                    else:
                        # URL 확장자로 추론 (매직 넘버로 감지 실패 시)
                        if '.png' in image_url.lower():
                            content_type = 'image/png'
                        elif '.gif' in image_url.lower():
                            content_type = 'image/gif'
                        elif '.webp' in image_url.lower():
                            content_type = 'image/webp'
                        else:
                            # 기본값: JPEG
                            content_type = 'image/jpeg'
                else:
                    # 데이터가 너무 짧으면 기본값 사용
                    content_type = 'image/jpeg'
            
            # Content-Type에서 charset 제거 (이미지에는 불필요)
            if ';' in content_type:
                content_type = content_type.split(';')[0].strip()
            
            # 최종적으로 image/로 시작하지 않으면 강제로 image/jpeg 설정
            if not content_type.startswith('image/'):
                content_type = 'image/jpeg'
            
            # 이미지 데이터를 HttpResponse로 반환 (인라인 표시)
            # Content-Type을 명시적으로 설정하여 브라우저가 이미지로 인식하도록 함
            http_response = HttpResponse(
                image_data,
                content_type=content_type
            )
            
            # Content-Disposition 헤더를 'inline'으로 명시적으로 설정
            # 다운로드가 아닌 브라우저 내에서 직접 표시되도록 함
            http_response['Content-Disposition'] = 'inline; filename="thumbnail.jpg"'
            
            # 캐싱 헤더 추가
            http_response['Cache-Control'] = 'public, max-age=3600'
            
            # CORS 헤더 추가 (필요한 경우)
            http_response['Access-Control-Allow-Origin'] = '*'
            
            # X-Content-Type-Options 헤더 추가 (브라우저가 Content-Type을 무시하지 않도록)
            http_response['X-Content-Type-Options'] = 'nosniff'
            
            return http_response
            
        except requests.exceptions.RequestException as e:
            logger.error(f"이미지 프록시 실패: {image_url}, 에러: {str(e)}")
            return Response(
                {'error': f'이미지를 가져올 수 없습니다: {str(e)}'},
                status=status.HTTP_502_BAD_GATEWAY
            )
        except Exception as e:
            logger.error(f"이미지 프록시 예외: {image_url}, 에러: {str(e)}")
            return Response(
                {'error': f'서버 오류: {str(e)}'},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )


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
            {'status': 'str'}
        )
        # GenericForeignKey는 select_related로 최적화할 수 없으므로
        # prefetch_related를 사용하거나 content_type만 select_related
        return queryset.select_related('content_type')


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
        중복 실행 방지: 최근 5분 이내에 실행 중인 세션이 있으면 새로 시작하지 않습니다.
        """
        # 중복 실행 방지: 최근 5분 이내에 실행 중인 News 세션이 있는지 확인
        recent_time = timezone.now() - timedelta(minutes=5)
        running_sessions = CollectionSession.objects.filter(
            status='running',
            started_at__gte=recent_time,
            total_sources__gt=0  # News 세션은 total_sources > 0
        )
        
        if running_sessions.exists():
            recent_session = running_sessions.order_by('-started_at').first()
            return Response({
                'status': 'already_running',
                'message': (
                    f'이미 뉴스 수집 작업이 실행 중입니다. '
                    f'세션 ID: {recent_session.id}, '
                    f'시작 시간: {recent_session.started_at.strftime("%Y-%m-%d %H:%M:%S")}'
                ),
                'session_id': recent_session.id
            }, status=status.HTTP_409_CONFLICT)
        
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
        중복 실행 방지: 최근 5분 이내에 실행 중인 세션이 있으면 새로 시작하지 않습니다.
        """
        # 중복 실행 방지: 최근 5분 이내에 실행 중인 Social Media 세션이 있는지 확인
        recent_time = timezone.now() - timedelta(minutes=5)
        running_sessions = CollectionSession.objects.filter(
            status='running',
            started_at__gte=recent_time
        )
        
        if running_sessions.exists():
            recent_session = running_sessions.order_by('-started_at').first()
            return Response({
                'status': 'already_running',
                'message': (
                    f'이미 소셜 미디어 수집 작업이 실행 중입니다. '
                    f'세션 ID: {recent_session.id}, '
                    f'시작 시간: {recent_session.started_at.strftime("%Y-%m-%d %H:%M:%S")}'
                ),
                'session_id': recent_session.id
            }, status=status.HTTP_409_CONFLICT)
        
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
        중복 실행 방지: 최근 5분 이내에 실행 중인 세션이 있으면 새로 시작하지 않습니다.
        """
        # 중복 실행 방지: 최근 5분 이내에 실행 중인 세션이 있는지 확인
        recent_time = timezone.now() - timedelta(minutes=5)
        running_sessions = CollectionSession.objects.filter(
            status='running',
            started_at__gte=recent_time
        )
        
        if running_sessions.exists():
            recent_session = running_sessions.order_by('-started_at').first()
            return Response({
                'status': 'already_running',
                'message': (
                    f'이미 수집 작업이 실행 중입니다. '
                    f'세션 ID: {recent_session.id}, '
                    f'시작 시간: {recent_session.started_at.strftime("%Y-%m-%d %H:%M:%S")}'
                ),
                'session_id': recent_session.id,
                'started_at': recent_session.started_at.isoformat()
            }, status=status.HTTP_409_CONFLICT)
        
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
