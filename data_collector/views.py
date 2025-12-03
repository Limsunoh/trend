"""
데이터 수집 API 뷰 모듈
"""
import logging
import csv
import os
from django.conf import settings
from rest_framework import viewsets, status
from rest_framework.decorators import action
from rest_framework.response import Response
from rest_framework.filters import SearchFilter, OrderingFilter
from django.db.models import QuerySet
from django.db import transaction
from .models import NewsSource, NewsArticle, SocialMediaPost, DataCollectionJob
from .serializers import (
    NewsSourceSerializer,
    NewsArticleSerializer,
    SocialMediaPostSerializer,
    DataCollectionJobSerializer
)
from .tasks import collect_rss_news_task, collect_all_rss_news_task
from .services import RSSCollectorService
from celery.result import AsyncResult

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

    def _load_sources_from_csv(self, csv_file_path: str = None) -> dict:
        """
        CSV 파일에서 NewsSource를 생성하는 헬퍼 함수
        
        Args:
            csv_file_path: CSV 파일 경로 (None이면 기본 경로 사용)
        
        Returns:
            결과 딕셔너리 (created, updated, skipped, errors, sources, error_details)
        """
        results = {
            'created': 0,
            'updated': 0,
            'skipped': 0,
            'errors': 0,
            'sources': [],
            'error_details': []  # 오류 상세 정보 추가
        }

        try:
            # CSV 파일 경로 결정
            if csv_file_path:
                csv_path = csv_file_path
            else:
                # 기본 경로: 프로젝트 루트의 NewsSource_RSS.csv
                csv_path = os.path.join(
                    settings.BASE_DIR,
                    'NewsSource_RSS.csv'
                )

            # CSV 파일 경로 확인
            if not os.path.exists(csv_path):
                logger.error(f"CSV 파일을 찾을 수 없습니다: {csv_path}")
                results['errors'] = 1
                return results

            # CSV 파일 읽기
            with open(csv_path, 'r', encoding='utf-8') as f:
                reader = csv.DictReader(f)

                for row in reader:
                    try:
                        publisher = row.get('publisher', '').strip()
                        category = row.get('title', '').strip()  # CSV의 title이 카테고리
                        url = row.get('url', '').strip()

                        # 필수 필드 검증
                        if not publisher or not url:
                            logger.warning(
                                f"필수 필드가 없는 행 건너뜀: {row}"
                            )
                            results['skipped'] += 1
                            continue

                        # 1. URL로 먼저 확인 (가장 정확)
                        existing_source = (
                            NewsSource.objects.filter(url=url).first()
                        )

                        # 2. URL이 없으면 publisher + category로 확인
                        if not existing_source:
                            existing_source = (
                                NewsSource.objects.filter(
                                    publisher=publisher,
                                    category=category
                                ).first()
                            )

                        if existing_source:
                            # 기존 소스 업데이트
                            updated_fields = []
                            
                            # URL이 다르면 업데이트
                            if existing_source.url != url:
                                existing_source.url = url
                                updated_fields.append('url')
                            
                            # publisher가 다르면 업데이트
                            if existing_source.publisher != publisher:
                                existing_source.publisher = publisher
                                updated_fields.append('publisher')
                            
                            # category가 다르면 업데이트
                            if existing_source.category != category:
                                existing_source.category = category
                                updated_fields.append('category')
                            
                            if updated_fields:
                                existing_source.save(update_fields=updated_fields)
                                logger.info(
                                    f"소스 업데이트: {publisher} - {category} ({url}) - "
                                    f"변경된 필드: {', '.join(updated_fields)}"
                                )
                            
                            results['updated'] += 1
                            serializer = NewsSourceSerializer(
                                existing_source
                            )
                            results['sources'].append(serializer.data)
                        else:
                            # 새 소스 생성
                            try:
                                with transaction.atomic():
                                    source = NewsSource.objects.create(
                                        publisher=publisher,
                                        category=category if category else None,
                                        url=url,
                                        source_type='rss',
                                        is_active=True,
                                        collection_interval=60
                                    )
                                    results['created'] += 1
                                    serializer = NewsSourceSerializer(source)
                                    results['sources'].append(serializer.data)
                                    logger.info(
                                        f"새 소스 생성: {publisher} - {category} ({url})"
                                    )
                            except Exception as create_error:
                                # 중복 오류인 경우, 기존 것을 찾아서 업데이트
                                if 'unique' in str(create_error).lower() or 'duplicate' in str(create_error).lower():
                                    existing_by_pub_cat = (
                                        NewsSource.objects.filter(
                                            publisher=publisher,
                                            category=category
                                        ).first()
                                    )
                                    if existing_by_pub_cat:
                                        existing_by_pub_cat.url = url
                                        existing_by_pub_cat.save(update_fields=['url'])
                                        results['updated'] += 1
                                        logger.info(
                                            f"중복으로 인한 업데이트: {publisher} - {category} "
                                            f"(URL 변경: {url})"
                                        )
                                        continue
                                # 다른 오류면 다시 raise
                                raise

                    except Exception as e:
                        error_msg = str(e)
                        logger.error(
                            f"소스 생성 오류 (행: {row}): {error_msg}",
                            exc_info=True
                        )
                        results['errors'] += 1
                        # 오류 상세 정보 저장
                        results['error_details'].append({
                            'row': row,
                            'error': error_msg,
                            'publisher': row.get('publisher', ''),
                            'title': row.get('title', ''),
                            'url': row.get('url', '')
                        })
                        continue

            logger.info(
                f"CSV 파일 로드 완료: 생성={results['created']}, "
                f"업데이트={results['updated']}, "
                f"건너뜀={results['skipped']}, "
                f"오류={results['errors']}"
            )

        except Exception as e:
            logger.error(
                f"CSV 파일 읽기 오류: {str(e)}",
                exc_info=True
            )
            results['errors'] = 1

        return results

    def create(self, request):
        """
        CSV 파일에서 NewsSource를 일괄 생성
        
        요청 파라미터:
            - csv_file: CSV 파일 경로 (선택, 없으면 기본 경로 사용)
        """
        # CSV 파일 경로 결정
        csv_file = (
            request.data.get('csv_file') or
            request.query_params.get('csv_file')
        )

        # CSV 파일 로드
        results = self._load_sources_from_csv(csv_file)

        # 응답 생성
        if results['errors'] > 0 and results['created'] == 0 and results['updated'] == 0:
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


class ArticleCreateViewSet(viewsets.ViewSet):
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


class NewsSourceViewSet(viewsets.ModelViewSet):
    """뉴스 소스 ViewSet"""
    queryset = NewsSource.objects.all()
    serializer_class = NewsSourceSerializer
    filter_backends = [SearchFilter, OrderingFilter]
    search_fields = ['name', 'url']
    ordering_fields = ['name', 'created_at', 'last_collected_at']
    ordering = ['-created_at']

    def get_queryset(self):
        queryset = NewsSource.objects.all()
        return filter_queryset_by_params(
            queryset, self.request,
            {'is_active': 'bool', 'source_type': 'str'}
        )

    @action(detail=True, methods=['post'])
    def collect(self, request, pk=None):
        """특정 소스에서 데이터 수집 시작"""
        source = NewsSource.objects.get(pk=pk)
        try:
            # Celery 태스크는 비동기 실행을 위해 delay() 사용
            task_result: AsyncResult = collect_rss_news_task.delay(
                source_id=source.id
            )
            logger.info(
                f"소스 수집 태스크 시작: {str(source)} "
                f"(ID: {source.id}, Task ID: {task_result.id})"
            )
            return Response({
                'status': 'started',
                'task_id': task_result.id,
                'message': f'{str(source)}에서 수집 작업이 시작되었습니다.',
                'source': str(source),
                'source_id': source.id
            }, status=status.HTTP_202_ACCEPTED)
        except Exception as e:
            logger.error(
                f"소스 수집 태스크 시작 실패: {str(source)} - {str(e)}",
                exc_info=True
            )
            return Response({
                'status': 'error',
                'message': f'수집 작업 시작 실패: {str(e)}',
                'source': str(source)
            }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)


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
        queryset = DataCollectionJob.objects.all()
        queryset = filter_queryset_by_params(
            queryset, self.request,
            {'source': 'int', 'status': 'str'}
        )
        return queryset.select_related('source')


class TriggerCollectionViewSet(viewsets.ViewSet):
    """데이터 수집 작업 트리거 ViewSet"""

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
        """데이터 수집 작업 시작 (POST /api/collector/trigger/)"""
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

            # 엄격한 검증: collect_all과 source_id/source_name을 동시에 사용할 수 없음
            if collect_all and (source_id or source_name):
                return Response({
                    'status': 'error',
                    'message': (
                        'collect_all과 source_id/source_name을 '
                        '동시에 사용할 수 없습니다.'
                    )
                }, status=status.HTTP_400_BAD_REQUEST)

            elif collect_all or (not source_id and not source_name):
                # 전체 수집: collect_all이 True이거나 파라미터가 모두 없을 때
                task_result = collect_all_rss_news_task.delay()
                logger.info(f"전체 소스 수집 태스크 시작 (Task ID: {task_result.id})")
                return Response({
                    'status': 'started',
                    'task_id': task_result.id,
                    'message': '모든 활성화된 소스에서 수집 작업이 시작되었습니다.',
                    'collect_all': True
                }, status=status.HTTP_202_ACCEPTED)

            # 특정 소스 수집: source_id 또는 source_name이 있을 때
            elif source_id or source_name:
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
            }, status=status.HTTP_404_NOT_FOUND)
