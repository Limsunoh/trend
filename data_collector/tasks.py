"""
데이터 수집 Celery 태스크 모듈

이 모듈은 Celery를 사용하여 비동기적으로 데이터를 수집하는 태스크들을 정의합니다.
주요 기능:
1. RSS 피드 수집 (경향신문 등)
2. 소셜 미디어 데이터 수집
3. Redis를 활용한 중복 방지, Rate Limiting, 통계 집계

태스크들은 RSSCollectorService 클래스를 사용하여 실제 수집 작업을 수행합니다.
"""
import logging
from typing import Optional
from celery import shared_task
from .services import RSSCollectorService
from .models import NewsSource
from common.redis_services import (
    DuplicatePreventionService,
    RateLimitService,
    RealtimeStatsService
)

# 로거 설정
logger = logging.getLogger(__name__)


@shared_task(bind=True, max_retries=3)
def collect_rss_news_task(self, source_id: Optional[int] = None, source_name: Optional[str] = None):
    """
    RSS 피드 수집 Celery 태스크 (클래스 기반)
    
    RSSCollectorService 클래스를 사용하여 RSS 피드에서 뉴스 기사를 수집합니다.
    경향신문뿐만 아니라 다른 뉴스 소스도 모두 처리할 수 있습니다.
    
    주요 기능:
    1. Redis를 사용한 중복 수집 방지
    2. Rate Limiting을 통한 API 호출 제한
    3. 실시간 통계 집계
    4. 수집 작업 로그 기록
    
    Args:
        source_id: NewsSource 모델의 ID (선택)
        source_name: NewsSource의 이름 (선택, 예: '경향신문')
        
    동작 과정:
        1. RSSCollectorService 인스턴스 생성
        2. NewsSource 조회
        3. 서비스 클래스의 collect_from_source() 메서드 호출
        4. 수집 결과 반환
        
    재시도 정책:
        - max_retries=3: 최대 3번까지 재시도
        - 네트워크 오류나 일시적 오류 발생 시 자동 재시도
        
    사용 예시:
        # 소스 ID로 수집
        collect_rss_news_task.delay(source_id=1)
        
        # 소스 이름으로 수집
        collect_rss_news_task.delay(source_name='경향신문')
        
        # 모든 활성화된 소스 수집 (source_id와 source_name 둘 다 None)
        collect_rss_news_task.delay()
    """
    try:
        # RSS 수집 서비스 인스턴스 생성
        # 서비스 클래스가 Redis 서비스들을 내부에서 초기화합니다.
        collector = RSSCollectorService()
        
        # 수집 실행
        # collect() 메서드는 source_id나 source_name을 받아서 처리합니다.
        result = collector.collect(source_id=source_id, source_name=source_name)
        
        logger.info(
            f"RSS 수집 태스크 완료: {result.get('source', 'All sources')} - "
            f"상태: {result.get('status')}"
        )
        
        return result
        
    except Exception as e:
        # 작업 실패 처리
        error_msg = f"RSS 수집 태스크 실패: {str(e)}"
        logger.error(error_msg, exc_info=True)
        
        # Celery 재시도
        # 네트워크 오류 등 일시적 오류의 경우 재시도합니다.
        raise self.retry(exc=e, countdown=60)  # 60초 후 재시도


@shared_task
def collect_all_rss_news_task():
    """
    모든 활성화된 RSS 소스에서 뉴스를 수집하는 Celery 태스크
    
    데이터베이스에 등록된 모든 활성화된 RSS 소스에 대해
    개별적으로 수집 태스크를 시작합니다.
    
    이 태스크는 주기적으로 실행되어 모든 뉴스 소스를 순회하며
    데이터를 수집합니다.
    
    각 소스는 별도의 비동기 태스크로 실행되므로,
    여러 소스를 동시에 수집할 수 있습니다.
    
    사용 예시:
        # 모든 활성화된 소스 수집 시작
        collect_all_rss_news_task.delay()
    """
    # 활성화된 모든 RSS 소스 조회
    news_sources = NewsSource.objects.filter(
        is_active=True,
        source_type='rss'
    )
    
    started_tasks = []
    failed_sources = []
    
    for source in news_sources:
        try:
            # 각 소스에 대해 수집 태스크 호출
            # delay()를 사용하여 비동기로 실행합니다.
            result = collect_rss_news_task.delay(source_id=source.id)
            started_tasks.append({
                'source_id': source.id,
                'source_name': source.name,
                'task_id': result.id
            })
            logger.info(f"수집 태스크 시작: {source.name} (Task ID: {result.id})")
        except Exception as e:
            failed_sources.append({
                'source_id': source.id,
                'source_name': source.name,
                'error': str(e)
            })
            logger.error(
                f"수집 태스크 시작 실패: {source.name} - {str(e)}",
                exc_info=True
            )
    
    return {
        'status': 'started',
        'sources_count': news_sources.count(),
        'started_tasks': started_tasks,
        'failed_sources': failed_sources,
        'message': f'{len(started_tasks)}개 뉴스 소스에 대한 수집 태스크를 시작했습니다.'
    }


@shared_task
def collect_news_task():
    """
    뉴스 데이터 수집 작업 (호환성 유지용)
    
    collect_all_rss_news_task()의 별칭입니다.
    기존 코드와의 호환성을 위해 유지됩니다.
    
    사용 예시:
        collect_news_task.delay()
    """
    return collect_all_rss_news_task.delay()


@shared_task
def collect_social_media_task():
    """
    소셜 미디어 데이터 수집 작업
    - 우선순위 2: 중복 데이터 수집 방지
    - 우선순위 4: API Rate Limiting
    - 우선순위 5: 실시간 통계 집계
    """
    duplicate_check = DuplicatePreventionService()
    rate_limit = RateLimitService()
    stats = RealtimeStatsService()
    
    # TODO: 소셜 미디어 플랫폼별 수집
    platforms = ['twitter', 'facebook']  # TODO: 설정에서 가져오기
    
    for platform in platforms:
        # 우선순위 4: Rate Limit 체크
        api_key = f"{platform}_api_key"  # TODO: 실제 API 키
        limit_check = rate_limit.check_rate_limit(
            identifier=api_key,
            max_requests=100,  # TODO: 플랫폼별 제한
            window_seconds=3600
        )
        
        if not limit_check['allowed']:
            continue
        
        # TODO: 소셜 미디어 게시물 가져오기
        posts = []  # TODO: 실제 API 호출
        
        for post in posts:
            post_id = post.get('id')
            
            # 우선순위 2: 중복 체크
            if duplicate_check.is_already_collected(platform, post_id):
                continue
            
            # TODO: 게시물 수집 및 저장
            # SocialMediaPost.objects.create(...)
            
            # 우선순위 2: 수집 완료 표시
            duplicate_check.mark_as_collected(platform, post_id)
            
            # 우선순위 5: 통계 업데이트
            stats.increment_counter(f'{platform}_posts_collected')
            stats.record_timestamp(f'{platform}_post_collected')
