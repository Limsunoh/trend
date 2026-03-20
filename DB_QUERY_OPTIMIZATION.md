# DB 쿼리 최적화 가이드

프로젝트는 Django ORM을 사용하며, **쿼리 수·소요 시간을 측정**하고 **필요 시 EXPLAIN으로 실행 계획**을 확인할 수 있습니다.

---

## 1. 쿼리 벤치마크 실행

주요 API에서 쓰는 조회 패턴의 쿼리 개수·소요 시간을 한 번에 측정합니다.

```bash
# 기본: 주요 시나리오 1회씩 측정
python manage.py benchmark_queries

# EXPLAIN (ANALYZE)로 실행 계획까지 출력 (인덱스 사용 여부 등 확인)
python manage.py benchmark_queries --explain

# 각 시나리오 5회 반복 후 평균 시간
python manage.py benchmark_queries --rounds 5
```

- **쿼리 개수**는 `DEBUG=True`일 때만 집계됩니다. 로컬에서 `.env`에 `DEBUG=True`로 두고 실행하세요.
- `DEBUG=False`여도 **경과 시간(wall time)** 은 항상 출력됩니다.

---

## 2. 코드 안에서 특정 블록만 측정

`common.db_profiling`의 `measure_queries` 컨텍스트 매니저를 사용합니다.

```python
from common.db_profiling import measure_queries, explain_queryset

# 블록 실행 시 쿼리 수·SQL 시간·경과 시간 출력
with measure_queries("뉴스 목록 조회"):
    list(NewsArticle.objects.select_related("source")[:20])

# 해당 QuerySet의 PostgreSQL 실행 계획 출력
explain_queryset(NewsArticle.objects.filter(category="정치")[:10])
```

---

## 3. ORM 최적화 체크리스트

| 항목 | 설명 |
|------|------|
| **select_related** | FK 1:1, N:1 조인 한 번에 가져오기. 뉴스/소셜 목록에서 `source` 사용 시 필수. |
| **prefetch_related** | 역참조·M2M 등 1:N을 별도 쿼리로 미리 가져와 N+1 방지. |
| **only / defer** | 필요한 컬럼만 조회해 대용량 테이블에서 부담 감소. |
| **인덱스** | `filter`, `order_by`에 자주 쓰는 필드는 `db_index=True` 또는 `Meta.indexes`. (이미 적용된 모델 많음) |
| **exists() 주의** | 슬라이스한 뒤 `qs.exists()`를 쓰면 쿼리가 2번 나갑니다. `results = list(qs); if not results: ...` 로 한 번만 조회. |
| **iterator()** | 수만 건 이상 스트리밍할 때 메모리 절약. 일반 목록 API에는 불필요. |

---

## 4. Raw SQL과 비교하고 싶을 때

ORM이 생성한 SQL이 느리다고 의심되면:

1. `python manage.py benchmark_queries --explain` 으로 실행 계획 확인.
2. `common.db_profiling.get_query_sql(queryset)` 로 SQL·파라미터 추출 후, 동일 조건으로 raw 쿼리 작성해 `cursor.execute()` 로 실행해 보며 시간 비교.
3. 인덱스 추가·복합 인덱스 조정 후 다시 `benchmark_queries` 및 `--explain`으로 확인.

---

## 5. 참고

- 모델별 인덱스는 `data_collector/models.py`, `analyzer/models.py` 등에 이미 다수 정의되어 있습니다.
- 대시보드·분석 목록 API는 Redis 캐시로 응답을 감싸 두어, 캐시 hit 시에는 DB 쿼리가 발생하지 않습니다.
