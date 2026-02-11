"""
시간대별 트렌드 변화 분석 관리 명령어

사용법:
    # 최근 7일간 시간대별 트렌드 분석 (뉴스 + SNS)
    python manage.py analyze_hourly_trends

    # 뉴스만 분석
    python manage.py analyze_hourly_trends --platform news

    # SNS만 분석
    python manage.py analyze_hourly_trends --platform sns

    # 최근 3일간, 시간대별 상위 5개 키워드만
    python manage.py analyze_hourly_trends --days 3 --top-n 5
"""

from django.core.management.base import BaseCommand

from analyzer.services import analyze_hourly_trends


class Command(BaseCommand):
    help = "시간대별 트렌드 변화를 분석합니다."

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
            "--min-frequency",
            type=float,
            default=0.001,
            help="최소 상대 빈도 (기본값: 0.001 = 0.1%%)",
        )

        parser.add_argument(
            "--top-n", type=int, help="시간대별 상위 N개 키워드만 출력 (None이면 전체)"
        )

    def handle(self, *args, **options):
        """명령어 실행"""
        platform = options["platform"]
        days = options["days"]
        min_frequency = options["min_frequency"]
        top_n = options.get("top_n")

        self.stdout.write("=" * 80)
        self.stdout.write(self.style.SUCCESS("시간대별 트렌드 분석 시작"))
        self.stdout.write("=" * 80)
        self.stdout.write(f"플랫폼: {platform}")
        self.stdout.write(f"분석 기간: 최근 {days}일")
        if top_n:
            self.stdout.write(f"시간대별 상위 {top_n}개 키워드 출력")
        self.stdout.write("")

        try:
            result = analyze_hourly_trends(
                platform=platform, days=days, min_frequency=min_frequency, top_n=top_n
            )

            # 뉴스 시간대별 트렌드 출력
            if result["news_hourly_trends"]:
                self.stdout.write(self.style.SUCCESS("\n[뉴스 시간대별 트렌드]"))
                self.stdout.write("=" * 80)

                for hour in range(24):
                    if hour in result["news_hourly_trends"]:
                        hour_data = result["news_hourly_trends"][hour]
                        self.stdout.write(
                            f"\n{hour:02d}시 ({hour_data['total_count']}개 게시물)"
                        )
                        self.stdout.write("-" * 80)

                        if hour_data["keywords"]:
                            for i, kw in enumerate(hour_data["keywords"], 1):
                                self.stdout.write(
                                    f"  {i}. {kw['keyword']} "
                                    f"(빈도: {kw['frequency']:.4f})"
                                )
                        else:
                            self.stdout.write("  (키워드 없음)")
            else:
                self.stdout.write(
                    self.style.WARNING("\n[뉴스] 시간대별 트렌드 데이터 없음")
                )

            # SNS 시간대별 트렌드 출력
            if result["sns_hourly_trends"]:
                self.stdout.write(self.style.SUCCESS("\n[SNS 시간대별 트렌드]"))
                self.stdout.write("=" * 80)

                for hour in range(24):
                    if hour in result["sns_hourly_trends"]:
                        hour_data = result["sns_hourly_trends"][hour]
                        self.stdout.write(
                            f"\n{hour:02d}시 ({hour_data['total_count']}개 게시물)"
                        )
                        self.stdout.write("-" * 80)

                        if hour_data["keywords"]:
                            for i, kw in enumerate(hour_data["keywords"], 1):
                                self.stdout.write(
                                    f"  {i}. {kw['keyword']} "
                                    f"(빈도: {kw['frequency']:.4f})"
                                )
                        else:
                            self.stdout.write("  (키워드 없음)")
            else:
                self.stdout.write(
                    self.style.WARNING("\n[SNS] 시간대별 트렌드 데이터 없음")
                )

            # 요약 통계
            summary = result["summary"]
            self.stdout.write(self.style.SUCCESS("\n[요약 통계]"))
            self.stdout.write("-" * 80)
            self.stdout.write(f"뉴스 분석된 시간대: {summary['news_hours_analyzed']}개")
            self.stdout.write(f"SNS 분석된 시간대: {summary['sns_hours_analyzed']}개")

        except Exception as e:
            self.stdout.write(self.style.ERROR(f"시간대별 트렌드 분석 실패: {str(e)}"))
            raise
