"""
키워드 분석 관리 명령어

사용법:
    # 최근 7일간 분석
    python manage.py analyze_keywords

    # 최근 30일간 분석
    python manage.py analyze_keywords --days 30

    # 상위 20개 키워드만
    python manage.py analyze_keywords --top-n 20

    # 플랫폼 비교 분석
    python manage.py analyze_keywords --compare

    # 뉴스만 분석
    python manage.py analyze_keywords --news-only

    # SNS만 분석
    python manage.py analyze_keywords --sns-only
"""

from django.core.management.base import BaseCommand

from analyzer.services import (
    analyze_news_articles,
    analyze_sns_posts,
    compare_platforms,
)


class Command(BaseCommand):
    help = "뉴스와 SNS 데이터에서 키워드를 추출하고 분석합니다."

    def add_arguments(self, parser):
        """명령어 인자 추가"""
        parser.add_argument(
            "--days",
            type=int,
            default=7,
            help="최근 며칠간의 데이터를 분석할지 (기본값: 7)",
        )

        parser.add_argument(
            "--top-n", type=int, default=50, help="상위 N개 키워드만 표시 (기본값: 50)"
        )

        parser.add_argument(
            "--compare", action="store_true", help="뉴스와 SNS 플랫폼 비교 분석 수행"
        )

        parser.add_argument(
            "--news-only", action="store_true", help="뉴스만 분석 (SNS 제외)"
        )

        parser.add_argument(
            "--sns-only", action="store_true", help="SNS만 분석 (뉴스 제외)"
        )

        parser.add_argument(
            "--min-frequency",
            type=float,
            default=0.001,
            help="최소 상대 빈도 (기본값: 0.001 = 0.1%%)",
        )

    def handle(self, *args, **options):
        """명령어 실행"""
        days = options["days"]
        top_n = options["top_n"]
        compare = options["compare"]
        news_only = options["news_only"]
        sns_only = options["sns_only"]
        min_frequency = options["min_frequency"]

        self.stdout.write("=" * 80)
        self.stdout.write(self.style.SUCCESS("키워드 분석 시작"))
        self.stdout.write("=" * 80)
        self.stdout.write(f"분석 기간: 최근 {days}일")
        self.stdout.write(f"상위 키워드: {top_n}개")
        self.stdout.write("")

        # 플랫폼 비교 분석
        if compare:
            self._compare_platforms(days, top_n, min_frequency)

        # 뉴스만 분석
        elif news_only:
            self._analyze_news(days, top_n)

        # SNS만 분석
        elif sns_only:
            self._analyze_sns(days, top_n)

        # 둘 다 분석
        else:
            self._analyze_both(days, top_n)

        self.stdout.write("")
        self.stdout.write("=" * 80)
        self.stdout.write(self.style.SUCCESS("분석 완료"))
        self.stdout.write("=" * 80)

    def _analyze_news(self, days: int, top_n: int):
        """뉴스만 분석"""
        self.stdout.write("\n[뉴스 기사 분석]")
        self.stdout.write("-" * 80)

        try:
            result = analyze_news_articles(days=days, top_n=top_n)

            self.stdout.write(
                self.style.SUCCESS(
                    f"✅ 분석 완료: {result['total_articles']}개 기사, "
                    f"{result['total_keywords']}개 키워드"
                )
            )

            if result["top_keywords"]:
                self.stdout.write("\n상위 키워드:")
                for i, item in enumerate(result["top_keywords"], 1):
                    keyword = item["keyword"]
                    freq = item["frequency"]
                    abs_count = result["absolute_frequency"].get(keyword, 0)
                    self.stdout.write(
                        f"  {i:2d}. {keyword:20s} "
                        f"빈도: {freq:.4f} ({freq*100:.2f}%) "
                        f"절대: {abs_count}회"
                    )
            else:
                self.stdout.write(self.style.WARNING("키워드가 없습니다."))

        except Exception as e:
            self.stdout.write(self.style.ERROR(f"❌ 분석 실패: {str(e)}"))

    def _analyze_sns(self, days: int, top_n: int):
        """SNS만 분석"""
        self.stdout.write("\n[SNS 게시물 분석]")
        self.stdout.write("-" * 80)

        try:
            result = analyze_sns_posts(days=days, top_n=top_n)

            self.stdout.write(
                self.style.SUCCESS(
                    f"✅ 분석 완료: {result['total_posts']}개 게시물, "
                    f"{result['total_keywords']}개 키워드"
                )
            )

            if result["top_keywords"]:
                self.stdout.write("\n상위 키워드:")
                for i, item in enumerate(result["top_keywords"], 1):
                    keyword = item["keyword"]
                    freq = item["frequency"]
                    abs_count = result["absolute_frequency"].get(keyword, 0)
                    self.stdout.write(
                        f"  {i:2d}. {keyword:20s} "
                        f"빈도: {freq:.4f} ({freq*100:.2f}%) "
                        f"절대: {abs_count}회"
                    )
            else:
                self.stdout.write(self.style.WARNING("키워드가 없습니다."))

        except Exception as e:
            self.stdout.write(self.style.ERROR(f"❌ 분석 실패: {str(e)}"))

    def _analyze_both(self, days: int, top_n: int):
        """뉴스와 SNS 둘 다 분석"""
        self._analyze_news(days, top_n)
        self.stdout.write("")
        self._analyze_sns(days, top_n)

    def _compare_platforms(self, days: int, top_n: int, min_frequency: float):
        """플랫폼 비교 분석"""
        self.stdout.write("\n[플랫폼 비교 분석]")
        self.stdout.write("-" * 80)

        try:
            result = compare_platforms(
                days=days, top_n=top_n, min_frequency=min_frequency
            )

            summary = result["summary"]
            self.stdout.write(
                self.style.SUCCESS(
                    f"✅ 분석 완료:\n"
                    f"  - 뉴스: {summary['total_news_articles']}개 기사, "
                    f"{summary['news_keywords_count']}개 키워드\n"
                    f"  - SNS: {summary['total_sns_posts']}개 게시물, "
                    f"{summary['sns_keywords_count']}개 키워드\n"
                    f"  - 공통 키워드: {summary['common_keywords_count']}개"
                )
            )

            if result["common_keywords"]:
                self.stdout.write("\n공통 키워드 비교:")
                for i, item in enumerate(result["common_keywords"], 1):
                    keyword = item["keyword"]
                    news_freq = item["news_frequency"]
                    sns_freq = item["sns_frequency"]
                    diff = item["difference"]
                    diff_str = f"+{diff:.4f}" if diff > 0 else f"{diff:.4f}"

                    self.stdout.write(
                        f"  {i:2d}. {keyword:20s}\n"
                        f"      뉴스: {news_freq:.4f} ({news_freq*100:.2f}%) "
                        f"[{item['news_absolute']}회]\n"
                        f"      SNS:  {sns_freq:.4f} ({sns_freq*100:.2f}%) "
                        f"[{item['sns_absolute']}회]\n"
                        f"      차이: {diff_str} "
                        f"({'SNS가 더 높음' if diff > 0 else '뉴스가 더 높음'})"
                    )
            else:
                self.stdout.write(self.style.WARNING("공통 키워드가 없습니다."))

            # 뉴스에만 있는 키워드 (상위 10개)
            if result["news_only"]:
                self.stdout.write("\n뉴스에만 있는 키워드 (상위 10개):")
                sorted_news_only = sorted(
                    result["news_only"].items(), key=lambda x: x[1], reverse=True
                )[:10]
                for i, (keyword, freq) in enumerate(sorted_news_only, 1):
                    self.stdout.write(
                        f"  {i:2d}. {keyword:20s} " f"{freq:.4f} ({freq*100:.2f}%)"
                    )

            # SNS에만 있는 키워드 (상위 10개)
            if result["sns_only"]:
                self.stdout.write("\nSNS에만 있는 키워드 (상위 10개):")
                sorted_sns_only = sorted(
                    result["sns_only"].items(), key=lambda x: x[1], reverse=True
                )[:10]
                for i, (keyword, freq) in enumerate(sorted_sns_only, 1):
                    self.stdout.write(
                        f"  {i:2d}. {keyword:20s} " f"{freq:.4f} ({freq*100:.2f}%)"
                    )

        except Exception as e:
            self.stdout.write(self.style.ERROR(f"❌ 비교 분석 실패: {str(e)}"))
