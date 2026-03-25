"""데이터 수집 Celery 태스크 모듈."""

import json
import logging
from datetime import timedelta
from typing import Optional

from celery import current_app, shared_task
from django.contrib.contenttypes.models import ContentType
from django.db import transaction
from django.utils import timezone

from common.redis_services import RedisService

from .models import (
    CollectionSession,
    DataCollectionJob,
    NewsArticle,
    NewsSource,
    SocialMediaPost,
    SocialMediaSource,
)
from .report_service import CollectionReportService
from .services import (
    DCInsideCollectorService,
    RedditRSSCollectorService,
    RSSCollectorService,
)

# 로거 설정
logger = logging.getLogger(__name__)

RETENTION_DAYS_DEFAULT = 12


def _delete_queryset_in_chunks(queryset, chunk_size: int = 2000) -> int:
    """대량 삭제 시 DB 부하를 줄이기 위해 청크 단위로 삭제합니다."""
    deleted_total = 0
    while True:
        ids = list(queryset.values_list("id", flat=True)[:chunk_size])
        if not ids:
            break
        with transaction.atomic():
            deleted_count, _ = queryset.model.objects.filter(id__in=ids).delete()
        deleted_total += int(deleted_count)
    return deleted_total


@shared_task
def cleanup_old_data_task(
    retention_days: int = RETENTION_DAYS_DEFAULT, dry_run: bool = False
):
    """
    보관 기간이 지난 수집/분석 데이터를 자동 정리합니다.

    기본 보관 기간은 12일이며, cutoff 이전 데이터가 삭제 대상입니다.
    """
    if retention_days < 1:
        retention_days = RETENTION_DAYS_DEFAULT

    cutoff = timezone.now() - timedelta(days=retention_days)
    stats = {
        "retention_days": retention_days,
        "cutoff": cutoff.isoformat(),
        "dry_run": dry_run,
        "deleted": {},
    }

    from analyzer.models import TrendAnalysisResult
    from user_qa.models import QueryHistory

    targets = [
        (
            "trend_analysis_results",
            TrendAnalysisResult.objects.filter(created_at__lt=cutoff),
        ),
        ("query_history", QueryHistory.objects.filter(created_at__lt=cutoff)),
        ("news_articles", NewsArticle.objects.filter(collected_at__lt=cutoff)),
        ("social_media_posts", SocialMediaPost.objects.filter(collected_at__lt=cutoff)),
        (
            "data_collection_jobs",
            DataCollectionJob.objects.filter(started_at__lt=cutoff),
        ),
        (
            "collection_sessions",
            CollectionSession.objects.filter(started_at__lt=cutoff),
        ),
    ]

    for label, qs in targets:
        if dry_run:
            count = qs.count()
            stats["deleted"][label] = count
            continue
        deleted_count = _delete_queryset_in_chunks(qs)
        stats["deleted"][label] = deleted_count

    # Chroma 벡터DB도 동일 cutoff 기준으로 정리
    if not dry_run:
        try:
            from user_qa.services import VectorDBService

            vdb = VectorDBService()
            vdb.delete_old_documents(cutoff.isoformat())
            stats["chroma_cleanup"] = "success"
        except Exception as e:
            logger.warning(f"[데이터 보관정리] Chroma 정리 실패: {e}")
            stats["chroma_cleanup"] = f"failed: {e}"

    logger.info(
        "[데이터 보관정리] retention_days=%s cutoff=%s dry_run=%s deleted=%s",
        stats["retention_days"],
        stats["cutoff"],
        stats["dry_run"],
        stats["deleted"],
    )
    return stats


@shared_task(bind=True, max_retries=3)
def collect_rss_news_task(
    self,
    source_id: Optional[int] = None,
    source_name: Optional[str] = None,
    session_id: Optional[int] = None,
):
    """RSS 뉴스 수집 태스크. 단일 소스 또는 전체 소스를 수집합니다."""
    try:
        collector = RSSCollectorService()

        result = collector.collect(source_id=source_id, source_name=source_name)

        logger.info(
            f"RSS 수집 태스크 완료: {result.get('source', 'All sources')} - "
            f"상태: {result.get('status')}"
        )

        if session_id:
            try:
                session = CollectionSession.objects.get(id=session_id)
                _update_session_stats(session, result)
            except CollectionSession.DoesNotExist:
                logger.warning(f"세션을 찾을 수 없습니다: session_id={session_id}")

        return result

    except Exception as e:
        error_msg = f"RSS 수집 태스크 실패: {str(e)}"
        logger.error(error_msg, exc_info=True)

        if session_id:
            try:
                session = CollectionSession.objects.get(id=session_id)
                session.failed_sources += 1
                session.save()
            except CollectionSession.DoesNotExist:
                pass

        raise self.retry(exc=e, countdown=60)  # 60초 후 재시도


@shared_task
def collect_all_rss_news_task(run_id: Optional[str] = None):
    """활성 RSS 소스 전체 수집을 시작하고 세션을 생성합니다."""
    notes = "session_type:news"
    if run_id:
        notes = f"session_type:news run_id:{run_id}"
    session = CollectionSession.objects.create(
        status="running", started_at=timezone.now(), notes=notes
    )

    news_sources = NewsSource.objects.filter(is_active=True, source_type="rss")

    session.total_sources = news_sources.count()
    session.save()

    started_tasks = []
    failed_sources = []

    for source in news_sources:
        try:
            result = collect_rss_news_task.delay(
                source_id=source.id, session_id=session.id
            )
            started_tasks.append(
                {
                    "source_id": source.id,
                    "source_name": str(source),
                    "task_id": result.id,
                }
            )
            logger.info(
                f"수집 태스크 시작: {str(source)} "
                f"(Task ID: {result.id}, Session ID: {session.id})"
            )
        except Exception as e:
            failed_sources.append(
                {"source_id": source.id, "source_name": str(source), "error": str(e)}
            )
            logger.error(
                f"수집 태스크 시작 실패: {str(source)} - {str(e)}", exc_info=True
            )
            session.failed_sources += 1
            session.save()

    logger.info(
        f"수집 세션 시작: Session ID={session.id}, "
        f"총 {session.total_sources}개 소스"
    )

    check_session_completion.delay(session.id)

    return {
        "status": "started",
        "session_id": session.id,
        "sources_count": news_sources.count(),
        "started_tasks": started_tasks,
        "failed_sources": failed_sources,
        "message": f"{len(started_tasks)}개 뉴스 소스에 대한 수집 태스크를 시작했습니다.",
    }


def _update_session_stats(session: CollectionSession, result: dict):
    """세션 통계 업데이트"""
    status = result.get("status", "")

    if status == "completed":
        session.successful_sources += 1
        session.total_articles_collected += result.get("items_collected", 0)
        session.total_articles_skipped += result.get("items_skipped", 0)
        session.total_articles_error += result.get("items_error", 0)
    elif status in ["failed", "rate_limited"]:
        session.failed_sources += 1

    session.save()


def _trigger_embedding_for_session(session_id: int, session_type: str):
    """세션 완료 후 임베딩 태스크를 트리거합니다."""
    try:
        triggered_tasks = []

        if session_type in ("news", "unknown"):
            task = current_app.send_task(
                "user_qa.tasks.embed_recent_news_articles_task",
                kwargs={"since": None, "collection": None, "limit": 5000},
                queue="embedding",
            )
            triggered_tasks.append(("news", task.id))
            logger.info(
                f"[자동 임베딩 트리거][뉴스] 세션 #{session_id} 완료 후 "
                f"임베딩 태스크 등록: task_id={task.id}"
            )

        if session_type in ("social", "unknown"):
            task = current_app.send_task(
                "user_qa.tasks.embed_recent_social_posts_task",
                kwargs={"since": None, "collection": None, "limit": 5000},
                queue="embedding",
            )
            triggered_tasks.append(("social", task.id))
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
            f"[자동 임베딩 트리거 실패] 세션 #{session_id}: {str(e)}", exc_info=True
        )
        return []


def _trigger_analysis_after_full_collect(
    days: int = 7, top_n: int = 50, platform: str = "both"
):
    """뉴스+소셜 완료 시 후속 분석 태스크를 트리거합니다."""
    try:
        app = current_app
        tasks_to_send = [
            ("analyzer.analyze_keywords_task", {"days": days, "top_n": top_n}),
            (
                "analyzer.compare_platforms_task",
                {"days": days, "top_n": min(30, top_n)},
            ),
            ("analyzer.update_hot_keywords", {"days": 1, "top_n": 20}),
            ("analyzer.analyze_time_lag_task", {"days": days, "top_n": top_n}),
            (
                "analyzer.detect_surge_keywords_task",
                {"platform": platform, "days": days},
            ),
            ("analyzer.analyze_trend_synchronization_task", {"days": days}),
            (
                "analyzer.analyze_hourly_trends_task",
                {"platform": platform, "days": days},
            ),
            ("analyzer.analyze_engagement_keywords_task", {"days": days}),
        ]
        for task_name, kwargs in tasks_to_send:
            app.send_task(task_name, kwargs=kwargs)
        logger.info(
            "[자동 분석 트리거] 뉴스+소셜 세션 완료 후 8개 분석 태스크 등록 완료"
        )
    except Exception as e:
        logger.error(f"[자동 분석 트리거 실패] {str(e)}", exc_info=True)


@shared_task
def check_session_completion(session_id: int):
    """세션 완료 여부를 점검하고 완료 시 리포트를 생성합니다."""
    try:
        session = CollectionSession.objects.get(id=session_id)
    except CollectionSession.DoesNotExist:
        logger.error(f"세션을 찾을 수 없습니다: session_id={session_id}")
        return

    if session.status != "running":
        logger.info(
            f"세션 #{session.id}은 이미 {session.status} 상태입니다. "
            f"체크를 중단합니다."
        )
        return

    session.refresh_from_db()
    if session.status != "running":
        logger.info(
            f"세션 #{session.id}이 {session.status} 상태로 변경되었습니다. "
            f"체크를 중단합니다."
        )
        return

    jobs = DataCollectionJob.objects.filter(started_at__gte=session.started_at)

    # notes의 session_type을 기준으로 해당 세션 작업만 집계
    session_type_from_notes = None
    if session.notes and "session_type:" in (session.notes or ""):
        session_type_from_notes = (
            session.notes.split("session_type:")[-1].strip().split()[0]
        )

    if session_type_from_notes == "news":
        news_content_type = ContentType.objects.get_for_model(NewsSource)
        jobs = jobs.filter(content_type=news_content_type)
    elif session_type_from_notes == "social":
        social_content_type = ContentType.objects.get_for_model(SocialMediaSource)
        jobs = jobs.filter(content_type=social_content_type)
    else:
        # 레거시 세션 fallback
        first_job = jobs.order_by("started_at").first()
        if first_job and first_job.content_type:
            if first_job.content_type.model == "newssource":
                news_content_type = ContentType.objects.get_for_model(NewsSource)
                jobs = jobs.filter(content_type=news_content_type)
            elif first_job.content_type.model == "socialmediasource":
                social_content_type = ContentType.objects.get_for_model(
                    SocialMediaSource
                )
                jobs = jobs.filter(content_type=social_content_type)

    completed_jobs = jobs.filter(status="completed").count()
    failed_jobs = jobs.filter(status="failed").count()
    running_jobs = jobs.filter(status="running").count()

    time_since_start = timezone.now() - session.started_at
    all_tasks_done = (
        running_jobs == 0 and (completed_jobs + failed_jobs) >= session.total_sources
    )

    if all_tasks_done or time_since_start > timedelta(hours=2):
        if session.status == "running":
            session.mark_completed()

            try:
                celery_app = current_app
                inspect = celery_app.control.inspect()
                scheduled = inspect.scheduled() or {}
                reserved = inspect.reserved() or {}

                cancelled_count = 0
                for worker, tasks in {**scheduled, **reserved}.items():
                    for task in tasks:
                        task_name = task.get("name", "") or task.get("task", "")
                        task_args = task.get("args", []) or task.get("request", {}).get(
                            "args", []
                        )

                        if (
                            "check_session_completion" in task_name
                            and session_id in task_args
                        ):
                            task_id = task.get("id") or task.get("request", {}).get(
                                "id"
                            )
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

            try:
                report_service = CollectionReportService()
                reports = report_service.generate_all_reports(session)

                session.json_report_path = reports["json_path"]
                session.markdown_report_path = reports["markdown_path"]
                session.save()

                logger.info(
                    f"세션 #{session.id} 완료 및 리포트 생성: "
                    f"JSON={reports['json_path']}, "
                    f"Markdown={reports['markdown_path']}"
                )
            except Exception as e:
                logger.error(
                    f"리포트 생성 실패 (Session ID={session.id}): {str(e)}",
                    exc_info=True,
                )

            embedding_session_type = session_type_from_notes or "unknown"
            _trigger_embedding_for_session(session.id, embedding_session_type)

            run_id = None
            if session.notes and "run_id:" in session.notes:
                idx = session.notes.find("run_id:")
                if idx >= 0:
                    run_id = session.notes[idx + 7 :].strip().split()[0]
            if run_id:
                try:
                    redis_svc = RedisService()
                    redis_key = f"full_collect_run:{run_id}"
                    raw = redis_svc.client.get(redis_key)
                    if raw:
                        data = json.loads(raw)
                        if session_type_from_notes == "news":
                            data["news_done"] = True
                        elif session_type_from_notes == "social":
                            data["social_done"] = True
                        if data.get("news_done") and data.get("social_done"):
                            redis_svc.client.delete(redis_key)
                            _trigger_analysis_after_full_collect(
                                days=data.get("days", 7),
                                top_n=data.get("top_n", 50),
                                platform=data.get("platform", "both"),
                            )
                        else:
                            redis_svc.client.setex(redis_key, 7200, json.dumps(data))
                except Exception as e:
                    logger.warning(
                        f"[full_collect 분석 트리거] run_id={run_id} Redis 처리 실패: {e}"
                    )
    else:
        # 아직 완료되지 않으면 5분 후 재체크
        session.refresh_from_db()
        if session.status == "running":
            remaining = session.total_sources - (completed_jobs + failed_jobs)
            logger.info(
                f"세션 #{session.id} 아직 진행 중. "
                f"남은 작업: 약 {remaining}개. 5분 후 다시 체크합니다."
            )
            check_session_completion.apply_async(args=[session_id], countdown=300)
        else:
            logger.info(
                f"세션 #{session.id}이 {session.status} 상태로 변경되었습니다. "
                f"체크를 중단합니다."
            )


@shared_task
def collect_news_task():
    """뉴스 전체 수집 태스크의 호환용 별칭."""
    return collect_all_rss_news_task.delay()


@shared_task(bind=True, max_retries=3)
def collect_dcinside_task(
    self, source_id: Optional[int] = None, session_id: Optional[int] = None
):
    """DC Inside 게시글 수집 태스크."""
    try:
        collector = DCInsideCollectorService()

        result = collector.collect_from_source(source_id=source_id)

        logger.info(
            f"DC Inside 수집 태스크 완료: {result.get('source', 'Unknown')} - "
            f"상태: {result.get('status')}"
        )

        if session_id:
            try:
                session = CollectionSession.objects.get(id=session_id)
                _update_social_media_session_stats(session, result)
            except CollectionSession.DoesNotExist:
                logger.warning(f"세션을 찾을 수 없습니다: session_id={session_id}")

        return result

    except Exception as e:
        error_msg = f"DC Inside 수집 태스크 실패: {str(e)}"
        logger.error(error_msg, exc_info=True)

        if session_id:
            try:
                session = CollectionSession.objects.get(id=session_id)
                session.failed_sources += 1
                session.save()
            except CollectionSession.DoesNotExist:
                pass

        raise self.retry(exc=e, countdown=60)  # 60초 후 재시도


@shared_task(bind=True, max_retries=3)
def collect_reddit_rss_task(
    self, source_id: Optional[int] = None, session_id: Optional[int] = None
):
    """Reddit RSS 수집 태스크."""
    try:
        collector = RedditRSSCollectorService()

        result = collector.collect_from_source(source_id=source_id)

        logger.info(
            f"Reddit RSS 수집 태스크 완료: {result.get('source', 'Unknown')} - "
            f"상태: {result.get('status')}"
        )

        if session_id:
            try:
                session = CollectionSession.objects.get(id=session_id)
                _update_social_media_session_stats(session, result)
            except CollectionSession.DoesNotExist:
                logger.warning(f"세션을 찾을 수 없습니다: session_id={session_id}")

        return result

    except Exception as e:
        error_msg = f"Reddit RSS 수집 태스크 실패: {str(e)}"
        logger.error(error_msg, exc_info=True)

        if session_id:
            try:
                session = CollectionSession.objects.get(id=session_id)
                session.failed_sources += 1
                session.save()
            except CollectionSession.DoesNotExist:
                pass

        raise self.retry(exc=e, countdown=60)  # 60초 후 재시도


@shared_task
def collect_all_social_media_task(run_id: Optional[str] = None):
    """활성 소셜 소스 전체 수집을 시작하고 세션을 생성합니다."""
    notes = "session_type:social"
    if run_id:
        notes = f"session_type:social run_id:{run_id}"
    session = CollectionSession.objects.create(
        status="running", started_at=timezone.now(), notes=notes
    )

    social_media_sources = SocialMediaSource.objects.filter(is_active=True)

    session.total_sources = social_media_sources.count()
    session.save()

    started_tasks = []
    failed_sources = []

    for source in social_media_sources:
        try:
            if source.platform == "dcinside":
                result = collect_dcinside_task.delay(
                    source_id=source.id, session_id=session.id
                )
            elif source.platform == "reddit":
                result = collect_reddit_rss_task.delay(
                    source_id=source.id, session_id=session.id
                )
            else:
                logger.warning(
                    f"지원하지 않는 플랫폼: {source.platform} "
                    f"(소스 ID: {source.id})"
                )
                failed_sources.append(
                    {
                        "source_id": source.id,
                        "source_name": str(source),
                        "error": f"지원하지 않는 플랫폼: {source.platform}",
                    }
                )
                session.failed_sources += 1
                session.save()
                continue

            started_tasks.append(
                {
                    "source_id": source.id,
                    "source_name": str(source),
                    "platform": source.platform,
                    "task_id": result.id,
                }
            )
            logger.info(
                f"소셜 미디어 수집 태스크 시작: {str(source)} "
                f"(플랫폼: {source.platform}, "
                f"Task ID: {result.id}, Session ID: {session.id})"
            )
        except Exception as e:
            failed_sources.append(
                {"source_id": source.id, "source_name": str(source), "error": str(e)}
            )
            logger.error(
                f"소셜 미디어 수집 태스크 시작 실패: {str(source)} - {str(e)}",
                exc_info=True,
            )
            session.failed_sources += 1
            session.save()

    logger.info(
        f"소셜 미디어 수집 세션 시작: Session ID={session.id}, "
        f"총 {session.total_sources}개 소스"
    )

    check_session_completion.delay(session.id)

    return {
        "status": "started",
        "session_id": session.id,
        "sources_count": social_media_sources.count(),
        "started_tasks": started_tasks,
        "failed_sources": failed_sources,
        "message": (
            f"{len(started_tasks)}개 소셜 미디어 소스에 대한 "
            f"수집 태스크를 시작했습니다."
        ),
    }


def _update_social_media_session_stats(session: CollectionSession, result: dict):
    """소셜 미디어 수집 세션 통계를 업데이트합니다."""
    status = result.get("status", "")

    if status == "success":
        session.successful_sources += 1
        session.total_articles_collected += result.get("items_collected", 0)
        session.total_articles_skipped += result.get("items_skipped", 0)
        session.total_articles_error += result.get("items_error", 0)
    elif status == "error":
        session.failed_sources += 1

    session.save()


@shared_task
def collect_social_media_task():
    """소셜 전체 수집 태스크의 호환용 별칭."""
    return collect_all_social_media_task.delay()
