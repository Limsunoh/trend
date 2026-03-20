"""
DB 쿼리 프로파일링 유틸리티.

- 쿼리 개수·총 SQL 시간 측정 (DEBUG=True일 때 connection.queries 사용)
- 특정 블록/함수 실행 시 쿼리 수·소요 시간 출력
- PostgreSQL EXPLAIN (ANALYZE)로 실행 계획 확인

사용 예:
    from common.db_profiling import measure_queries, explain_queryset

    with measure_queries("뉴스 목록 조회"):
        list(NewsArticle.objects.select_related("source")[:20])

    explain_queryset(NewsArticle.objects.filter(category="정치")[:10])
"""

import time
from contextlib import contextmanager
from typing import Any, Callable, Generator, List, Tuple

from django.conf import settings
from django.db import connection
from django.db.models import QuerySet


@contextmanager
def measure_queries(
    label: str = "queries",
    verbose: bool = True,
) -> Generator[dict, None, None]:
    """
    블록 실행 동안 발생한 DB 쿼리 개수와 소요 시간을 측정합니다.

    DEBUG=True일 때: connection.queries에서 쿼리별 시간 합산.
    DEBUG=False일 때: 쿼리 수는 알 수 없고, 블록 전체 wall-clock 시간만 측정.

    Yields:
        dict: {"query_count": int, "sql_time_ms": float, "wall_time_ms": float}
              DEBUG=False면 query_count=-1, sql_time_ms=0
    """
    if getattr(connection, "queries", None) is not None:
        try:
            from django.db import reset_queries

            reset_queries()
        except Exception:
            pass
    start_wall = time.perf_counter()
    result = {"query_count": -1, "sql_time_ms": 0.0, "wall_time_ms": 0.0}
    try:
        yield result
    finally:
        result["wall_time_ms"] = (time.perf_counter() - start_wall) * 1000
        if settings.DEBUG and getattr(connection, "queries", None) is not None:
            queries = connection.queries
            result["query_count"] = len(queries)
            try:
                # Django 4.x: connection.queries 각 항목의 "time"은 초 단위
                result["sql_time_ms"] = (
                    sum(float(q.get("time", 0)) for q in queries) * 1000
                )
            except (TypeError, ValueError):
                result["sql_time_ms"] = 0.0
        if verbose:
            qc = result["query_count"]
            sql_ms = result["sql_time_ms"]
            wall_ms = result["wall_time_ms"]
            if qc >= 0:
                print(
                    f"[db_profiling] {label}: queries={qc}, sql_time={sql_ms:.2f}ms, wall={wall_ms:.2f}ms"
                )
            else:
                print(
                    f"[db_profiling] {label}: wall={wall_ms:.2f}ms (set DEBUG=True for query count)"
                )


def get_query_sql(queryset: QuerySet) -> Tuple[str, List[Any]]:
    """QuerySet의 컴파일된 SQL과 파라미터를 반환합니다."""
    comp = queryset.query.get_compiler(connection.alias)
    sql, params = comp.as_sql()
    return sql, list(params)


def explain_queryset(
    queryset: QuerySet,
    analyze: bool = True,
    verbose: bool = True,
) -> List[str]:
    """
    PostgreSQL EXPLAIN (ANALYZE)를 실행해 실행 계획을 반환합니다.

    analyze=True면 실제 쿼리를 한 번 실행해 예상 비용과 실제 시간을 봅니다.
    """
    sql, params = get_query_sql(queryset)
    if not sql.strip().upper().startswith("SELECT"):
        if verbose:
            print("[db_profiling] EXPLAIN is only supported for SELECT queries.")
        return []
    explain_sql = "EXPLAIN (ANALYZE, FORMAT TEXT) " + sql
    with connection.cursor() as cursor:
        cursor.execute(explain_sql, params)
        rows = cursor.fetchall()
    lines = [row[0] for row in rows] if rows else []
    if verbose and lines:
        print(
            f"[db_profiling] EXPLAIN {'ANALYZE ' if analyze else ''}:\n"
            + "\n".join(lines)
        )
    return lines


def run_and_measure(
    label: str,
    fn: Callable[..., Any],
    *args: Any,
    **kwargs: Any,
) -> tuple[Any, dict]:
    """
    함수를 실행하면서 measure_queries로 감싼 결과와 반환값을 함께 반환합니다.

    Returns:
        (fn(*args, **kwargs) 결과, measure_queries 결과 dict)
    """
    with measure_queries(label, verbose=True) as stats:
        out = fn(*args, **kwargs)
    return out, stats
