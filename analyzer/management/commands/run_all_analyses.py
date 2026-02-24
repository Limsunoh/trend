from django.core.management.base import BaseCommand


class Command(BaseCommand):
    help = "트렌드 분석을 모두 실행합니다."

    def add_arguments(self, parser):
        parser.add_argument(
            "--days",
            type=int,
            default=7,
            help="분석 기간(일). 기본값: 7",
        )
        parser.add_argument(
            "--async",
            dest="use_async",
            action="store_true",
            help="Celery 비동기 실행(.delay). 워커가 떠 있어야 함.",
        )
        parser.add_argument(
            "--keyword",
            type=str,
            default="트렌드",
            help="단일 키워드 분석용 키워드 (등장 시간, 키워드 타임라인). 기본: 트렌드",
        )
        parser.add_argument(
            "--keywords",
            type=str,
            default="트렌드,분석",
            help="다중 키워드 타임라인용 키워드(쉼표 구분). 기본: 트렌드,분석",
        )
        parser.add_argument(
            "--platform",
            type=str,
            choices=["news", "sns", "both"],
            default="both",
            help="플랫폼(급상승·시간대별 등). 기본: both",
        )
        parser.add_argument(
            "--top-n",
            type=int,
            default=50,
            help="상위 N개 키워드 등. 기본: 50",
        )

    def handle(self, *args, **options):
        from analyzer import tasks

        days = options["days"]
        use_async = options["use_async"]
        keyword = (options["keyword"] or "트렌드").strip()
        keywords_str = (options["keywords"] or "트렌드,분석").strip()
        keywords_list = [k.strip() for k in keywords_str.split(",") if k.strip()]
        platform = options["platform"]
        top_n = options["top_n"]

        if use_async:
            self._run_async(tasks, days, keyword, keywords_list, platform, top_n)
        else:
            self._run_sync(tasks, days, keyword, keywords_list, platform, top_n)

    def _run_sync(self, tasks, days, keyword, keywords_list, platform, top_n):
        """동기 실행: .apply()로 현재 프로세스에서 순차 실행"""
        self.stdout.write("전체 분석을 동기로 실행합니다 (Celery 워커 불필요)...\n")

        steps = [
            (
                "키워드 분석",
                lambda: tasks.analyze_keywords_task.apply(
                    args=[], kwargs={"days": days, "top_n": top_n}
                ),
            ),
            (
                "플랫폼 비교 분석",
                lambda: tasks.compare_platforms_task.apply(
                    args=[], kwargs={"days": days, "top_n": min(30, top_n)}
                ),
            ),
            (
                "인기 키워드 분석",
                lambda: tasks.update_hot_keywords.apply(
                    args=[], kwargs={"days": min(1, days), "top_n": min(20, top_n)}
                ),
            ),
            (
                "시간차 분석",
                lambda: tasks.analyze_time_lag_task.apply(
                    args=[], kwargs={"days": days, "top_n": top_n}
                ),
            ),
            (
                "급상승 키워드 분석",
                lambda: tasks.detect_surge_keywords_task.apply(
                    args=[], kwargs={"platform": platform, "days": days}
                ),
            ),
            (
                "트렌드 동기화 분석",
                lambda: tasks.analyze_trend_synchronization_task.apply(
                    args=[], kwargs={"days": days}
                ),
            ),
            (
                "시간대별 트렌드 분석",
                lambda: tasks.analyze_hourly_trends_task.apply(
                    args=[], kwargs={"platform": platform, "days": days}
                ),
            ),
            (
                "참여도 기반 키워드 분석",
                lambda: tasks.analyze_engagement_keywords_task.apply(
                    args=[], kwargs={"days": days}
                ),
            ),
        ]

        for name, run in steps:
            try:
                self.stdout.write(f"  실행 중: {name} ... ", ending="")
                result = run().get()
                status = result.get("status", "ok")
                self.stdout.write(self.style.SUCCESS(f"완료 ({status})"))
            except Exception as e:
                self.stdout.write(self.style.ERROR(f"실패: {e}"))

        self.stdout.write(self.style.SUCCESS("\n전체 분석 실행이 끝났습니다."))

    def _run_async(self, tasks, days, keyword, keywords_list, platform, top_n):
        """비동기 실행: .delay()로 Celery 큐에 넣기"""
        self.stdout.write(
            "전체 분석을 Celery 비동기로 큐에 넣습니다 (워커가 처리합니다)...\n"
        )

        tasks.analyze_keywords_task.delay(days=days, top_n=top_n)
        tasks.compare_platforms_task.delay(days=days, top_n=min(30, top_n))
        tasks.update_hot_keywords.delay(days=min(1, days), top_n=min(20, top_n))
        tasks.analyze_time_lag_task.delay(days=days, top_n=top_n)
        tasks.detect_surge_keywords_task.delay(platform=platform, days=days)
        tasks.analyze_trend_synchronization_task.delay(days=days)
        tasks.analyze_hourly_trends_task.delay(platform=platform, days=days)
        tasks.analyze_engagement_keywords_task.delay(days=days)

        self.stdout.write(
            self.style.SUCCESS(
                "8개 분석 작업이 큐에 등록되었습니다. Celery 워커 로그를 확인하세요."
            )
        )
