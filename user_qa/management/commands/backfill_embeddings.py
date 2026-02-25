"""
미처리(is_processed=False) 뉴스/소셜 데이터를 소급 임베딩하는 Management Command.

사용법:
    # 전체 소급 임베딩 (뉴스 + 소셜)
    python manage.py backfill_embeddings

    # 뉴스만
    python manage.py backfill_embeddings --type news

    # 소셜만 (특정 플랫폼)
    python manage.py backfill_embeddings --type social --platform reddit

    # 처리 건수 제한
    python manage.py backfill_embeddings --limit 1000

    # Celery 큐에 비동기 등록 (워커 필요)
    python manage.py backfill_embeddings --async
"""

from __future__ import annotations

from django.core.management.base import BaseCommand

from user_qa.tasks import (
    embed_recent_news_articles_task,
    embed_recent_social_posts_task,
)


class Command(BaseCommand):
    help = (
        "DB에 저장된 미처리(is_processed=False) 뉴스/소셜 데이터를 소급 임베딩합니다."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--type",
            type=str,
            default="all",
            choices=["all", "news", "social"],
            help="임베딩 대상 (all/news/social)",
        )
        parser.add_argument(
            "--collection",
            type=str,
            default=None,
            help="Chroma 컬렉션 이름 (기본값: settings.CHROMA_COLLECTION)",
        )
        parser.add_argument(
            "--limit",
            type=int,
            default=5000,
            help="최대 처리 건수 (기본값: 5000)",
        )
        parser.add_argument(
            "--platform",
            type=str,
            default=None,
            help="소셜 플랫폼 필터 (reddit/dcinside)",
        )
        parser.add_argument(
            "--async",
            action="store_true",
            dest="use_async",
            help="Celery 큐에 비동기 등록 (워커가 실행 중이어야 함)",
        )

    def handle(self, *args, **opts):
        data_type = opts["type"]
        collection = opts["collection"]
        limit = opts["limit"]
        platform = opts["platform"]
        use_async = opts["use_async"]

        kwargs_news = {"since": None, "collection": collection, "limit": limit}
        kwargs_social = {
            "since": None,
            "collection": collection,
            "limit": limit,
            "platform": platform,
        }

        if use_async:
            self._run_async(data_type, kwargs_news, kwargs_social)
        else:
            self._run_sync(data_type, kwargs_news, kwargs_social)

    def _run_async(self, data_type, kwargs_news, kwargs_social):
        """Celery 큐에 비동기 등록"""
        if data_type in ("all", "news"):
            task = embed_recent_news_articles_task.delay(**kwargs_news)
            self.stdout.write(
                self.style.SUCCESS(f"[뉴스] Celery 태스크 등록 완료: task_id={task.id}")
            )

        if data_type in ("all", "social"):
            task = embed_recent_social_posts_task.delay(**kwargs_social)
            self.stdout.write(
                self.style.SUCCESS(f"[소셜] Celery 태스크 등록 완료: task_id={task.id}")
            )

        self.stdout.write(
            self.style.WARNING(
                "비동기 모드: Celery embedding 워커가 실행 중이어야 처리됩니다."
            )
        )

    def _run_sync(self, data_type, kwargs_news, kwargs_social):
        """현재 프로세스에서 동기 실행 (Celery 불필요)"""
        if data_type in ("all", "news"):
            self.stdout.write("[뉴스] 소급 임베딩 시작...")
            try:
                result = embed_recent_news_articles_task.apply(kwargs=kwargs_news)
                if result.successful():
                    info = result.result
                    self.stdout.write(
                        self.style.SUCCESS(
                            f"[뉴스] 완료: 처리기사={info.get('processed_articles', 0)}, "
                            f"생성청크={info.get('upserted_chunks', 0)}"
                        )
                    )
                else:
                    self.stderr.write(self.style.ERROR(f"[뉴스] 실패: {result.result}"))
            except Exception as e:
                self.stderr.write(self.style.ERROR(f"[뉴스] 예외 발생: {e}"))

        if data_type in ("all", "social"):
            self.stdout.write("[소셜] 소급 임베딩 시작...")
            try:
                result = embed_recent_social_posts_task.apply(kwargs=kwargs_social)
                if result.successful():
                    info = result.result
                    self.stdout.write(
                        self.style.SUCCESS(
                            f"[소셜] 완료: 처리게시물={info.get('processed_posts', 0)}, "
                            f"생성청크={info.get('upserted_chunks', 0)}"
                        )
                    )
                else:
                    self.stderr.write(self.style.ERROR(f"[소셜] 실패: {result.result}"))
            except Exception as e:
                self.stderr.write(self.style.ERROR(f"[소셜] 예외 발생: {e}"))
