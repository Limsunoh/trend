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
from datetime import timedelta
from celery import shared_task, current_app
from django.utils import timezone
from django.contrib.contenttypes.models import ContentType
from .services import (
    RSSCollectorService,
    DCInsideCollectorService,
    RedditRSSCollectorService
)
from .models import (
    NewsSource,
    SocialMediaSource,
    CollectionSession,
    DataCollectionJob
)
from .report_service import CollectionReportService

# 로거 설정
logger = logging.getLogger(__name__)


@shared_task(bind=True, max_retries=3)
def collect_rss_news_task(
    self,
    source_id: Optional[int] = None,
    source_name: Optional[str] = None,
    session_id: Optional[int] = None
):
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
        session_id: CollectionSession ID (선택, 세션 통계 업데이트용)
        
    동작 과정:
        1. RSSCollectorService 인스턴스 생성
        2. NewsSource 조회
        3. 서비스 클래스의 collect_from_source() 메서드 호출
        4. 수집 결과 반환
        5. 세션 통계 업데이트 (session_id가 있는 경우)
        
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
        result = collector.collect(
            source_id=source_id,
            source_name=source_name
        )
        
        logger.info(
            f"RSS 수집 태스크 완료: {result.get('source', 'All sources')} - "
            f"상태: {result.get('status')}"
        )
        
        # 세션 통계 업데이트
        if session_id:
            try:
                session = CollectionSession.objects.get(id=session_id)
                _update_session_stats(session, result)
            except CollectionSession.DoesNotExist:
                logger.warning(f"세션을 찾을 수 없습니다: session_id={session_id}")
        
        return result
        
    except Exception as e:
        # 작업 실패 처리
        error_msg = f"RSS 수집 태스크 실패: {str(e)}"
        logger.error(error_msg, exc_info=True)
        
        # 세션 통계 업데이트 (실패)
        if session_id:
            try:
                session = CollectionSession.objects.get(id=session_id)
                session.failed_sources += 1
                session.save()
            except CollectionSession.DoesNotExist:
                pass
        
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
    
    수집이 완료되면 자동으로 리포트(JSON, 마크다운)를 생성합니다.
    
    사용 예시:
        # 모든 활성화된 소스 수집 시작
        collect_all_rss_news_task.delay()
    """
    # 수집 세션 생성
    session = CollectionSession.objects.create(
        status='running',
        started_at=timezone.now(),
        notes='session_type:news'
    )

    # 활성화된 모든 RSS 소스 조회
    news_sources = NewsSource.objects.filter(
        is_active=True,
        source_type='rss'
    )

    session.total_sources = news_sources.count()
    session.save()
    
    started_tasks = []
    failed_sources = []
    
    for source in news_sources:
        try:
            # 각 소스에 대해 수집 태스크 호출 (session_id 전달)
            # delay()를 사용하여 비동기로 실행합니다.
            result = collect_rss_news_task.delay(
                source_id=source.id,
                session_id=session.id
            )
            started_tasks.append({
                'source_id': source.id,
                'source_name': str(source),
                'task_id': result.id
            })
            logger.info(
                f"수집 태스크 시작: {str(source)} "
                f"(Task ID: {result.id}, Session ID: {session.id})"
            )
        except Exception as e:
            failed_sources.append({
                'source_id': source.id,
                'source_name': str(source),
                'error': str(e)
            })
            logger.error(
                f"수집 태스크 시작 실패: {str(source)} - {str(e)}",
                exc_info=True
            )
            # 실패한 소스 카운트 증가
            session.failed_sources += 1
            session.save()
    
    logger.info(
        f"수집 세션 시작: Session ID={session.id}, "
        f"총 {session.total_sources}개 소스"
    )
    
    # 세션 완료 체크 및 리포트 생성 태스크 예약
    # 모든 작업이 완료된 후 리포트를 생성하기 위해 체크 태스크를 실행
    check_session_completion.delay(session.id)
    
    return {
        'status': 'started',
        'session_id': session.id,
        'sources_count': news_sources.count(),
        'started_tasks': started_tasks,
        'failed_sources': failed_sources,
        'message': f'{len(started_tasks)}개 뉴스 소스에 대한 수집 태스크를 시작했습니다.'
    }


def _update_session_stats(session: CollectionSession, result: dict):
    """세션 통계 업데이트"""
    status = result.get('status', '')

    if status == 'completed':
        session.successful_sources += 1
        session.total_articles_collected += result.get('items_collected', 0)
        session.total_articles_skipped += result.get('items_skipped', 0)
        session.total_articles_error += result.get('items_error', 0)
    elif status in ['failed', 'rate_limited']:
        session.failed_sources += 1

    session.save()


def _trigger_embedding_for_session(session_id: int, session_type: str):
    """
    세션 완료 후 임베딩 태스크를 자동으로 트리거합니다.

    Args:
        session_id: 완료된 CollectionSession의 ID
        session_type: 'news', 'social', 또는 'unknown'

    임베딩 태스크는 'embedding' 큐로 라우팅되며,
    실패해도 세션 완료 처리에는 영향을 주지 않습니다.
    """
    try:
        triggered_tasks = []

        if session_type in ('news', 'unknown'):
            task = current_app.send_task(
                'user_qa.tasks.embed_recent_news_articles_task',
                kwargs={'since': None, 'collection': None, 'limit': 5000},
                queue='embedding',
            )
            triggered_tasks.append(('news', task.id))
            logger.info(
                f"[자동 임베딩 트리거][뉴스] 세션 #{session_id} 완료 후 "
                f"임베딩 태스크 등록: task_id={task.id}"
            )

        if session_type in ('social', 'unknown'):
            task = current_app.send_task(
                'user_qa.tasks.embed_recent_social_posts_task',
                kwargs={'since': None, 'collection': None, 'limit': 5000},
                queue='embedding',
            )
            triggered_tasks.append(('social', task.id))
            logger.info(
                f"[자동 임베딩 트리거][소셜] 세션 #{session_id} 완료 후 "
                f"임베딩 태스크 등록: task_id={task.id}"
            )

        if not triggered_tasks:
            logger.warning(
                f"[자동 임베딩 트리거] 세션 #{session_id}: "
                f"세션 타입 '{session_type}'에 해당하는 임베딩 태스크가 없습니다."
            )

        return triggered_tasks

    except Exception as e:
        logger.error(
            f"[자동 임베딩 트리거 실패] 세션 #{session_id}: {str(e)}",
            exc_info=True
        )
        return []


@shared_task
def check_session_completion(session_id: int):
    """
    세션 완료 여부를 체크하고, 완료되었으면 리포트 생성
    
    모든 작업이 완료되었는지 확인하고, 완료되면 리포트를 생성합니다.
    News와 Social Media 세션 모두 지원합니다.
    """
    try:
        session = CollectionSession.objects.get(id=session_id)
    except CollectionSession.DoesNotExist:
        logger.error(f"세션을 찾을 수 없습니다: session_id={session_id}")
        return
    
    # 이미 완료된 세션이면 더 이상 체크하지 않음
    if session.status != 'running':
        logger.info(
            f"세션 #{session.id}은 이미 {session.status} 상태입니다. "
            f"체크를 중단합니다."
        )
        return
    
    # 세션 상태를 DB에서 다시 조회 (캐시 문제 방지)
    session.refresh_from_db()
    if session.status != 'running':
        logger.info(
            f"세션 #{session.id}이 {session.status} 상태로 변경되었습니다. "
            f"체크를 중단합니다."
        )
        return
    
    # 세션 시작 이후의 작업 확인
    jobs = DataCollectionJob.objects.filter(
        started_at__gte=session.started_at
    )

    # ✅ 세션 타입 판별: notes 필드에 저장된 session_type 사용 (동시 수집 시 혼선 방지)
    session_type_from_notes = None
    if session.notes and 'session_type:' in (session.notes or ''):
        session_type_from_notes = session.notes.split('session_type:')[-1].strip().split()[0]

    if session_type_from_notes == 'news':
        news_content_type = ContentType.objects.get_for_model(NewsSource)
        jobs = jobs.filter(content_type=news_content_type)
    elif session_type_from_notes == 'social':
        social_content_type = ContentType.objects.get_for_model(SocialMediaSource)
        jobs = jobs.filter(content_type=social_content_type)
    else:
        # notes가 없는 레거시 세션: 기존 방식(first_job 기반)으로 fallback
        first_job = jobs.order_by('started_at').first()
        if first_job and first_job.content_type:
            if first_job.content_type.model == 'newssource':
                news_content_type = ContentType.objects.get_for_model(NewsSource)
                jobs = jobs.filter(content_type=news_content_type)
            elif first_job.content_type.model == 'socialmediasource':
                social_content_type = ContentType.objects.get_for_model(SocialMediaSource)
                jobs = jobs.filter(content_type=social_content_type)
    
    completed_jobs = jobs.filter(status='completed').count()
    failed_jobs = jobs.filter(status='failed').count()
    running_jobs = jobs.filter(status='running').count()
    
    # 모든 작업 완료 여부 확인
    time_since_start = timezone.now() - session.started_at
    all_tasks_done = (
        running_jobs == 0 and
        (completed_jobs + failed_jobs) >= session.total_sources
    )
    
    # 2시간 이상 경과했거나 모든 작업이 완료되면 완료 처리
    if all_tasks_done or time_since_start > timedelta(hours=2):
        if session.status == 'running':
            session.mark_completed()
            
            # 세션 완료 시 이미 예약된 check_session_completion 태스크 취소
            try:
                celery_app = current_app
                inspect = celery_app.control.inspect()
                scheduled = inspect.scheduled() or {}
                reserved = inspect.reserved() or {}
                
                cancelled_count = 0
                for worker, tasks in {**scheduled, **reserved}.items():
                    for task in tasks:
                        task_name = task.get('name', '') or task.get('task', '')
                        task_args = task.get('args', []) or task.get('request', {}).get('args', [])
                        
                        if 'check_session_completion' in task_name and session_id in task_args:
                            task_id = task.get('id') or task.get('request', {}).get('id')
                            if task_id:
                                try:
                                    celery_app.control.revoke(task_id, terminate=True)
                                    cancelled_count += 1
                                except Exception:
                                    pass
                
                if cancelled_count > 0:
                    logger.info(
                        f"세션 #{session.id} 완료 시 "
                        f"{cancelled_count}개의 예약된 "
                        f"check_session_completion 태스크 취소"
                    )
            except Exception as e:
                logger.warning(f"예약된 태스크 취소 실패: {e}")
            
            # 리포트 생성
            try:
                report_service = CollectionReportService()
                reports = report_service.generate_all_reports(session)
                
                session.json_report_path = reports['json_path']
                session.markdown_report_path = reports['markdown_path']
                session.save()
                
                logger.info(
                    f"세션 #{session.id} 완료 및 리포트 생성: "
                    f"JSON={reports['json_path']}, "
                    f"Markdown={reports['markdown_path']}"
                )
            except Exception as e:
                logger.error(
                    f"리포트 생성 실패 (Session ID={session.id}): {str(e)}",
                    exc_info=True
                )

            # ✅ 자동 임베딩 트리거: 세션 완료 후 수집된 데이터를 벡터DB에 임베딩
            embedding_session_type = session_type_from_notes or 'unknown'
            _trigger_embedding_for_session(session.id, embedding_session_type)
    else:
        # 아직 완료되지 않았으면 5분 후 다시 체크
        # 단, 세션이 여전히 running 상태인지 확인
        # DB에서 최신 상태를 다시 조회
        session.refresh_from_db()
        if session.status == 'running':
            remaining = session.total_sources - (completed_jobs + failed_jobs)
            logger.info(
                f"세션 #{session.id} 아직 진행 중. "
                f"남은 작업: 약 {remaining}개. 5분 후 다시 체크합니다."
            )
            check_session_completion.apply_async(
                args=[session_id],
                countdown=300  # 5분 후
            )
        else:
            # 세션이 running 상태가 아니면 더 이상 체크하지 않음
            logger.info(
                f"세션 #{session.id}이 {session.status} 상태로 변경되었습니다. "
                f"체크를 중단합니다."
            )


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


@shared_task(bind=True, max_retries=3)
def collect_dcinside_task(
    self,
    source_id: Optional[int] = None,
    session_id: Optional[int] = None
):
    """
    DC Inside 갤러리 수집 Celery 태스크
    
    DCInsideCollectorService 클래스를 사용하여 DC Inside 갤러리에서 게시글을 수집합니다.
    
    주요 기능:
    1. DC Inside 갤러리 글 목록 수집
    2. 개별 게시글 상세 정보 수집
    3. 중복 수집 방지 (URL 기반)
    4. 수집 작업 로그 기록
    
    Args:
        source_id: SocialMediaSource 모델의 ID (선택)
        session_id: CollectionSession ID (선택, 세션 통계 업데이트용)
        
    재시도 정책:
        - max_retries=3: 최대 3번까지 재시도
        - 네트워크 오류나 일시적 오류 발생 시 자동 재시도
        
    사용 예시:
        # 소스 ID로 수집
        collect_dcinside_task.delay(source_id=1)
    """
    try:
        # DC Inside 수집 서비스 인스턴스 생성
        collector = DCInsideCollectorService()
        
        # 수집 실행
        result = collector.collect_from_source(source_id=source_id)
        
        logger.info(
            f"DC Inside 수집 태스크 완료: {result.get('source', 'Unknown')} - "
            f"상태: {result.get('status')}"
        )
        
        # 세션 통계 업데이트
        if session_id:
            try:
                session = CollectionSession.objects.get(id=session_id)
                _update_social_media_session_stats(session, result)
            except CollectionSession.DoesNotExist:
                logger.warning(f"세션을 찾을 수 없습니다: session_id={session_id}")
        
        return result
        
    except Exception as e:
        # 작업 실패 처리
        error_msg = f"DC Inside 수집 태스크 실패: {str(e)}"
        logger.error(error_msg, exc_info=True)
        
        # 세션 통계 업데이트 (실패)
        if session_id:
            try:
                session = CollectionSession.objects.get(id=session_id)
                session.failed_sources += 1
                session.save()
            except CollectionSession.DoesNotExist:
                pass
        
        # Celery 재시도
        raise self.retry(exc=e, countdown=60)  # 60초 후 재시도


@shared_task(bind=True, max_retries=3)
def collect_reddit_rss_task(
    self,
    source_id: Optional[int] = None,
    session_id: Optional[int] = None
):
    """
    Reddit RSS 피드 수집 Celery 태스크
    
    RedditRSSCollectorService 클래스를 사용하여 Reddit RSS 피드에서 게시글을 수집합니다.
    
    주요 기능:
    1. Reddit RSS 피드 파싱
    2. 중복 수집 방지 (URL 기반)
    3. 수집 작업 로그 기록
    
    Args:
        source_id: SocialMediaSource 모델의 ID (선택)
        session_id: CollectionSession ID (선택, 세션 통계 업데이트용)
        
    재시도 정책:
        - max_retries=3: 최대 3번까지 재시도
        - 네트워크 오류나 일시적 오류 발생 시 자동 재시도
        
    사용 예시:
        # 소스 ID로 수집
        collect_reddit_rss_task.delay(source_id=1)
    """
    try:
        # Reddit RSS 수집 서비스 인스턴스 생성
        collector = RedditRSSCollectorService()
        
        # 수집 실행
        result = collector.collect_from_source(source_id=source_id)
        
        logger.info(
            f"Reddit RSS 수집 태스크 완료: {result.get('source', 'Unknown')} - "
            f"상태: {result.get('status')}"
        )
        
        # 세션 통계 업데이트
        if session_id:
            try:
                session = CollectionSession.objects.get(id=session_id)
                _update_social_media_session_stats(session, result)
            except CollectionSession.DoesNotExist:
                logger.warning(f"세션을 찾을 수 없습니다: session_id={session_id}")
        
        return result
        
    except Exception as e:
        # 작업 실패 처리
        error_msg = f"Reddit RSS 수집 태스크 실패: {str(e)}"
        logger.error(error_msg, exc_info=True)
        
        # 세션 통계 업데이트 (실패)
        if session_id:
            try:
                session = CollectionSession.objects.get(id=session_id)
                session.failed_sources += 1
                session.save()
            except CollectionSession.DoesNotExist:
                pass
        
        # Celery 재시도
        raise self.retry(exc=e, countdown=60)  # 60초 후 재시도


@shared_task
def collect_all_social_media_task():
    """
    모든 활성화된 소셜 미디어 소스에서 데이터를 수집하는 Celery 태스크
    
    데이터베이스에 등록된 모든 활성화된 소셜 미디어 소스에 대해
    플랫폼별로 적절한 수집 태스크를 시작합니다.
    
    지원 플랫폼:
    - DC Inside: DCInsideCollectorService 사용
    - Reddit: RedditRSSCollectorService 사용
    
    각 소스는 별도의 비동기 태스크로 실행되므로,
    여러 소스를 동시에 수집할 수 있습니다.
    
    수집이 완료되면 자동으로 리포트(JSON, 마크다운)를 생성합니다.
    
    사용 예시:
        # 모든 활성화된 소셜 미디어 소스 수집 시작
        collect_all_social_media_task.delay()
    """
    # 수집 세션 생성
    session = CollectionSession.objects.create(
        status='running',
        started_at=timezone.now(),
        notes='session_type:social'
    )

    # 활성화된 모든 소셜 미디어 소스 조회
    social_media_sources = SocialMediaSource.objects.filter(
        is_active=True
    )

    session.total_sources = social_media_sources.count()
    session.save()
    
    started_tasks = []
    failed_sources = []
    
    for source in social_media_sources:
        try:
            # 플랫폼별로 적절한 태스크 선택
            if source.platform == 'dcinside':
                result = collect_dcinside_task.delay(
                    source_id=source.id,
                    session_id=session.id
                )
            elif source.platform == 'reddit':
                result = collect_reddit_rss_task.delay(
                    source_id=source.id,
                    session_id=session.id
                )
            else:
                logger.warning(
                    f"지원하지 않는 플랫폼: {source.platform} "
                    f"(소스 ID: {source.id})"
                )
                failed_sources.append({
                    'source_id': source.id,
                    'source_name': str(source),
                    'error': f'지원하지 않는 플랫폼: {source.platform}'
                })
                session.failed_sources += 1
                session.save()
                continue
            
            started_tasks.append({
                'source_id': source.id,
                'source_name': str(source),
                'platform': source.platform,
                'task_id': result.id
            })
            logger.info(
                f"소셜 미디어 수집 태스크 시작: {str(source)} "
                f"(플랫폼: {source.platform}, "
                f"Task ID: {result.id}, Session ID: {session.id})"
            )
        except Exception as e:
            failed_sources.append({
                'source_id': source.id,
                'source_name': str(source),
                'error': str(e)
            })
            logger.error(
                f"소셜 미디어 수집 태스크 시작 실패: {str(source)} - {str(e)}",
                exc_info=True
            )
            # 실패한 소스 카운트 증가
            session.failed_sources += 1
            session.save()
    
    logger.info(
        f"소셜 미디어 수집 세션 시작: Session ID={session.id}, "
        f"총 {session.total_sources}개 소스"
    )
    
    # 세션 완료 체크 및 리포트 생성 태스크 예약
    check_session_completion.delay(session.id)
    
    return {
        'status': 'started',
        'session_id': session.id,
        'sources_count': social_media_sources.count(),
        'started_tasks': started_tasks,
        'failed_sources': failed_sources,
        'message': (
            f'{len(started_tasks)}개 소셜 미디어 소스에 대한 '
            f'수집 태스크를 시작했습니다.'
        )
    }


def _update_social_media_session_stats(
    session: CollectionSession, result: dict
):
    """
    소셜 미디어 수집 세션 통계 업데이트
    
    RSS 수집과 동일한 구조로 통계를 업데이트합니다.
    """
    status = result.get('status', '')
    
    if status == 'success':
        session.successful_sources += 1
        session.total_articles_collected += result.get('items_collected', 0)
        session.total_articles_skipped += result.get('items_skipped', 0)
        session.total_articles_error += result.get('items_error', 0)
    elif status == 'error':
        session.failed_sources += 1
    
    session.save()


@shared_task
def collect_social_media_task():
    """
    소셜 미디어 데이터 수집 작업 (호환성 유지용)
    
    collect_all_social_media_task()의 별칭입니다.
    기존 코드와의 호환성을 위해 유지됩니다.
    
    사용 예시:
        collect_social_media_task.delay()
    """
    return collect_all_social_media_task.delay()
