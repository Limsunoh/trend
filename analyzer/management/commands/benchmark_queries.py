"""
DB 쿼리 벤치마크: 프로젝트에서 자주 쓰는 조회 패턴의 쿼리 수·소요 시간을 측정합니다.

사용법:
  python manage.py benchmark_queries              # 주요 목록/필터 쿼리 측정
  python manage.py benchmark_queries --explain     # EXPLAIN (ANALYZE) 출력
  python manage.py benchmark_queries --rounds 5   # 각 쿼리 5회 반복 후 평균

DEBUG=True일 때만 쿼리 개수가 집계됩니다. 로컬에서 DEBUG=True로 실행하세요.
"""

from django.conf import settings
from django.core.management.base import BaseCommand


class Command(BaseCommand):
    help = (
        "주요 ORM 쿼리 패턴의 쿼리 수·소요 시간을 측정합니다. "
        "DEBUG=True일 때 쿼리 개수 집계."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--explain",
            action="store_true",
            help="각 쿼리에 대해 PostgreSQL EXPLAIN (ANALYZE) 실행 계획 출력",
        )
        parser.add_argument(
            "--rounds",
            type=int,
            default=1,
            help="각 시나리오 반복 횟수 (평균 시간 출력). 기본: 1",
        )

    def handle(self, *args, **options):
        from common.db_profiling import measure_queries

        use_explain = options["explain"]
        rounds = max(1, options["rounds"])
        agg = "가능" if settings.DEBUG else "불가(시간만 측정)"
        self.stdout.write("DEBUG=%s → 쿼리 개수 집계 %s\n" % (settings.DEBUG, agg))

        scenarios = self._get_scenarios()
        for name, fn in scenarios:
            self.stdout.write("\n--- %s ---" % name)
            times_ms = []
            for r in range(rounds):
                with measure_queries(name, verbose=False) as stats:
                    fn()
                times_ms.append(stats["wall_time_ms"])
                if settings.DEBUG and stats["query_count"] >= 0 and rounds == 1:
                    self.stdout.write(
                        "  쿼리 수: %d, SQL 합계: %.2f ms, 경과: %.2f ms"
                        % (
                            stats["query_count"],
                            stats["sql_time_ms"],
                            stats["wall_time_ms"],
                        )
                    )
            if rounds > 1:
                avg = sum(times_ms) / len(times_ms)
                self.stdout.write("  평균 경과: %.2f ms (%d회)" % (avg, rounds))

            if use_explain:
                # EXPLAIN: fn과 동일한 queryset을 다시 만들어 실행 계획 출력
                self._run_explain_for(name)

        self.stdout.write("\n완료.")

    def _get_scenarios(self):
        """프로젝트 내 주요 조회 시나리오 (이름, 콜백) 목록."""

        def news_list():
            from data_collector.models import NewsArticle

            qs = NewsArticle.objects.select_related("source").order_by("-collected_at")
            list(qs[:20])

        def social_list():
            from data_collector.models import SocialMediaPost

            qs = SocialMediaPost.objects.select_related("source").order_by(
                "-collected_at"
            )
            list(qs[:20])

        def analysis_results_list():
            from analyzer.models import TrendAnalysisResult

            list(
                TrendAnalysisResult.objects.filter(status="success").order_by(
                    "-created_at"
                )[:10]
            )

        def query_history_list():
            from user_qa.models import QueryHistory

            list(QueryHistory.objects.all().order_by("-id")[:10])

        def trend_analysis_for_rag():
            """user_qa/services.py의 트렌드 분석 컨텍스트 조회와 동일한 패턴."""
            from analyzer.models import TrendAnalysisResult

            qs = TrendAnalysisResult.objects.filter(status="success").order_by(
                "-created_at"
            )[:5]
            # exists() 대신 리스트로 평가해 쿼리 1회로 처리 권장
            rows = list(qs)
            if not rows:
                return
            for result in rows:
                _ = result.analysis_type, result.result_data, result.summary

        return [
            ("뉴스 기사 목록 (select_related, 20건)", news_list),
            ("소셜 게시물 목록 (select_related, 20건)", social_list),
            ("트렌드 분석 결과 목록 (10건)", analysis_results_list),
            ("질의 히스토리 목록 (10건)", query_history_list),
            ("RAG용 트렌드 분석 결과 (5건)", trend_analysis_for_rag),
        ]

    def _run_explain_for(self, scenario_name: str):
        """시나리오 이름에 맞는 대표 QuerySet에 대해 EXPLAIN 실행."""
        from common.db_profiling import explain_queryset

        if "뉴스" in scenario_name:
            from data_collector.models import NewsArticle

            qs = NewsArticle.objects.select_related("source").order_by("-collected_at")[
                :5
            ]
        elif "소셜" in scenario_name:
            from data_collector.models import SocialMediaPost

            qs = SocialMediaPost.objects.select_related("source").order_by(
                "-collected_at"
            )[:5]
        elif "트렌드 분석 결과 목록" in scenario_name or "RAG용" in scenario_name:
            from analyzer.models import TrendAnalysisResult

            qs = TrendAnalysisResult.objects.filter(status="success").order_by(
                "-created_at"
            )[:5]
        elif "질의 히스토리" in scenario_name:
            from user_qa.models import QueryHistory

            qs = QueryHistory.objects.all().order_by("-id")[:5]
        else:
            return
        self.stdout.write("  [EXPLAIN]")
        explain_queryset(qs, analyze=True, verbose=True)
