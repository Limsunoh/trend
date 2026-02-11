"""
급상승 키워드 탐지 관리 명령어

사용법:
    # 최근 7일간 급상승 키워드 탐지 (뉴스 + SNS)
    python manage.py detect_surge_keywords

    # 뉴스만 분석
    python manage.py detect_surge_keywords --platform news

    # SNS만 분석
    python manage.py detect_surge_keywords --platform sns

    # 최근 3일간, 3배 이상 증가한 키워드만
    python manage.py detect_surge_keywords --days 3 --threshold 3.0

    # 상위 10개만 출력
    python manage.py detect_surge_keywords --top-n 10
"""

from django.core.management.base import BaseCommand

from analyzer.services import detect_surge_keywords


class Command(BaseCommand):
    help = "플랫폼별 급상승 키워드를 탐지합니다."

    def add_arguments(self, parser):
        """명령어 인자 추가"""
        parser.add_argument(
            "--platform",
            type=str,
            choices=["news", "sns", "both"],
            default="both",
            help="분석할 플랫폼 (기본값: both)",
        )

        parser.add_argument(
            "--days",
            type=int,
            default=7,
            help="최근 며칠간의 데이터를 분석할지 (기본값: 7)",
        )

        parser.add_argument(
            "--interval-hours",
            type=int,
            default=6,
            help="시간대별 집계 간격 (시간 단위, 기본값: 6)",
        )

        parser.add_argument(
            "--threshold",
            type=float,
            default=2.0,
            help="급상승 임계값 (이전 시간대 대비 배수, 기본값: 2.0 = 2배)",
        )

        parser.add_argument(
            "--min-frequency",
            type=float,
            default=0.001,
            help="최소 상대 빈도 (기본값: 0.001 = 0.1%%)",
        )

        parser.add_argument(
            "--top-n", type=int, help="상위 N개 급상승 키워드만 출력 (None이면 전체)"
        )

    def handle(self, *args, **options):
        """명령어 실행"""
        platform = options["platform"]
        days = options["days"]
        interval_hours = options["interval_hours"]
        surge_threshold = options["threshold"]
        min_frequency = options["min_frequency"]
        top_n = options.get("top_n")

        self.stdout.write("=" * 80)
        self.stdout.write(self.style.SUCCESS("급상승 키워드 탐지 시작"))
        self.stdout.write("=" * 80)
        self.stdout.write(f"플랫폼: {platform}")
        self.stdout.write(f"분석 기간: 최근 {days}일")
        self.stdout.write(f"시간대 간격: {interval_hours}시간")
        self.stdout.write(f"급상승 임계값: {surge_threshold}배 이상")
        self.stdout.write("")

        try:
            result = detect_surge_keywords(
                platform=platform,
                days=days,
                interval_hours=interval_hours,
                surge_threshold=surge_threshold,
                min_frequency=min_frequency,
                top_n=top_n,
            )

            # 뉴스 급상승 키워드 출력
            if result["news_surge_keywords"]:
                self.stdout.write(self.style.SUCCESS("\n[뉴스 급상승 키워드]"))
                self.stdout.write("-" * 80)
                for i, item in enumerate(result["news_surge_keywords"], 1):
                    self.stdout.write(
                        f"{i}. {item['keyword']} "
                        f"(증가율: {item['growth_ratio']:.2f}배, "
                        f"현재: {item['current_frequency']:.4f}, "
                        f"이전: {item['previous_frequency']:.4f})"
                    )
            else:
                self.stdout.write(self.style.WARNING("\n[뉴스] 급상승 키워드 없음"))

            # SNS 급상승 키워드 출력
            if result["sns_surge_keywords"]:
                self.stdout.write(self.style.SUCCESS("\n[SNS 급상승 키워드]"))
                self.stdout.write("-" * 80)
                for i, item in enumerate(result["sns_surge_keywords"], 1):
                    self.stdout.write(
                        f"{i}. {item['keyword']} "
                        f"(증가율: {item['growth_ratio']:.2f}배, "
                        f"현재: {item['current_frequency']:.4f}, "
                        f"이전: {item['previous_frequency']:.4f})"
                    )
            else:
                self.stdout.write(self.style.WARNING("\n[SNS] 급상승 키워드 없음"))

            # 요약 통계
            summary = result["summary"]
            self.stdout.write(self.style.SUCCESS("\n[요약 통계]"))
            self.stdout.write("-" * 80)
            self.stdout.write(f"뉴스 급상승 키워드: {summary['news_surge_count']}개")
            self.stdout.write(f"SNS 급상승 키워드: {summary['sns_surge_count']}개")

        except Exception as e:
            self.stdout.write(self.style.ERROR(f"급상승 키워드 탐지 실패: {str(e)}"))
            raise
