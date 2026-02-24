"""
강제로 전체 수집+분석 태스크를 큐에 넣습니다.
'최근 60분 내 실행 중인 수집 세션' 체크를 건너뜁니다. (테스트/긴급 실행용)
"""

from django.core.management.base import BaseCommand


class Command(BaseCommand):
    help = (
        "전체 수집+분석을 강제 실행 (실행 중인 수집 세션 체크 생략). "
        "Celery 워커가 떠 있어야 합니다."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--days",
            type=int,
            default=7,
            help="분석 기간(일). 기본 7",
        )
        parser.add_argument(
            "--top-n",
            type=int,
            default=50,
            help="상위 키워드 개수. 기본 50",
        )
        parser.add_argument(
            "--platform",
            type=str,
            choices=["news", "sns", "both"],
            default="both",
            help="플랫폼. 기본 both",
        )

    def handle(self, *args, **options):
        from analyzer.tasks import full_collect_and_analyze_task

        result = full_collect_and_analyze_task.delay(
            days=options["days"],
            top_n=options["top_n"],
            platform=options["platform"],
            force=True,
        )
        self.stdout.write(
            self.style.SUCCESS(
                f"전체 수집+분석 태스크가 큐에 등록되었습니다 (강제 실행). task_id={result.id}"
            )
        )
