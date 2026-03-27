# 단일 인스턴스 운영·튜닝 실행 가이드 (vCPU 2 / RAM 8GiB)

**전제:** 인스턴스를 늘리지 않는다. **웹 2대·로드밸런서·ASG·RDS Multi-AZ** 같은 다중화/확장 가이드는 이 문서에 넣지 않는다.  
**목표:** `LOADTEST.md` 기준과 같이 실패율 0%에 가깝게, 일반 API 평균·p95를 목표에 맞추고, 배포 시 **준무중단(near zero downtime)** 에 가깝게 만든다.

---

## 1. 현재 상태 (레포 기준, 한 번만 정리)

| 항목 | 내용 |
|------|------|
| 배포 | `.github/workflows/deploy.yml`에서 `docker compose down` 후 `up` → 배포 중 짧은 공백 가능 |
| Web | Gunicorn, `--workers 4`, `gevent`, `--worker-connections 500`, `--timeout 180` (`docker-compose.yml` `web`) |
| 안정화 옵션 | `--max-requests`, `--graceful-timeout`, `--keep-alive` 등은 **아직 compose에 없음** → 아래 절차에서 추가 |
| Redis 캐시 | 목록 API 등에 적용됨 (`CACHES`, `common/list_cache.py`) |
| 목록 TTL | `LIST_API_CACHE_TTL` 기본 **900초**(15분). `trend_analyzer/settings.py` + `.env` 없으면 900 적용 |
| Celery | 단일 `celery_worker`, `-Q celery,embedding` 혼합 (`--pool=solo`) |

---

## 2. 실행 우선순위 (이 순서 권장)

1. **연결 안정성** — Gunicorn 옵션 + OS/프록시 한도 점검 (실패율 0%에 가깝게)
2. **DB** — 느린 API 위주 `EXPLAIN ANALYZE`, 인덱스·N+1·직렬화
3. **캐시 TTL** — `.env`에서 `LIST_API_CACHE_TTL` 조정 (필요 시 코드로 엔드포인트별 분리)
4. **Celery** — `celery` / `embedding` 큐를 워커로 분리
5. **배포** — 준무중단(Blue/Green by Port) 도입 여부 결정

한 번에 여러 항목을 바꾸지 말고, **변경 1~2개 → Locust 동일 조건 재측정**으로 효과를 분리한다.

---

## 3. Gunicorn 안정화 (1순위, 이 섹션만 보면 됨)

**목적:** 워커 재시작 정책·우아 종료·Keep-Alive로 연결 끊김(`ConnectionResetError`, `RemoteDisconnected`) 감소.

`docker-compose.yml`의 `web` → `gunicorn` 줄에 아래를 **추가**한다 (값은 시작점이며, 부하 후 조정 가능).

| 옵션 | 의미 |
|------|------|
| `--max-requests 10000` | 요청 처리 N회마다 워커 재시작(메모리 누수·장기 상태 완화) |
| `--max-requests-jitter 1000` | 재시작 시점 분산 |
| `--graceful-timeout 30` | SIGTERM 후 기존 요청 마무리 허용 시간(초) |
| `--keep-alive 5` | HTTP Keep-Alive(초) |

**예시 (`command` 안 `exec gunicorn ...` 한 줄에 붙이기):**

```text
exec gunicorn --bind 0.0.0.0:8000 \
  --workers 4 --worker-class gevent --worker-connections 500 --timeout 180 \
  --graceful-timeout 30 --keep-alive 5 \
  --max-requests 10000 --max-requests-jitter 1000 \
  --access-logfile /app/logs/access.log --error-logfile /app/logs/error.log \
  trend_analyzer.wsgi:application
```

**적용·확인:**

```bash
docker compose up -d --force-recreate web
docker compose logs -f web
```

**검증:** 동일 Locust 시나리오에서 Failure%·연결 오류 로그 감소.

---

## 4. DB 쿼리 최적화 (2순위)

**우선 대상 API:**  
`/api/dashboard/news/`, `/api/dashboard/social/`, `/api/analyzer/analysis-results/`, `/api/analyzer/analysis/keywords/`, `/api/user_qa/history/`

**절차:**

1. Locust·access log로 느린 순위 3개 고정  
2. `EXPLAIN (ANALYZE, BUFFERS)` 로 실행계획 확인  
3. 인덱스, `select_related` / `prefetch_related`, 목록 응답 필드 축소  
4. 동일 조건 재측정 후 `LOADTEST.md` 기록  

**검증:** API 평균·p95 하락, RDS CPU/IO 피크 완화.

---

## 5. Redis 목록 캐시 TTL (3순위, 이 섹션만 보면 됨)

**현재 코드:** `LIST_API_CACHE_TTL = int(os.getenv("LIST_API_CACHE_TTL", "900"))` → `.env` 미설정 시 **900초**  
`common/list_cache.py`의 `get_list_cache_ttl()`이 이 값을 사용한다.

**1차 운영 권장 (단일 인스턴스):** `.env`에 `LIST_API_CACHE_TTL=120` 으로 시작 후, stale 민감도·DB 부하를 보며 조정.

**엔드포인트마다 다른 TTL이 필요하면:**  
코드에서 `set_cached_list_response()` 등에 prefix별 TTL 매핑을 추가하는 방식으로만 분리 가능(현재는 단일 환경변수).

**검증:** 캐시 히트율·DB read·사용자 체감 데이터 신선도.

---

## 6. Celery 큐 분리 (4순위)

**현재:** `celery -A trend_analyzer worker ... -Q celery,embedding --pool=solo` (한 프로세스)

**권장:** 서비스를 둘로 나눔.

- `celery_worker_default`: `-Q celery`  
- `celery_worker_embedding`: `-Q embedding`  

**2vCPU 시작 가이드:** default `-c 1~2`, embedding `-c 1` (pool 정책은 기존과 동일하게 유지하거나 팀 표준에 맞출 것).

**검증:** 임베딩 작업 몰림 시 일반 API p95 급등 완화.

---

## 7. 관측 (최소)

CloudWatch·Sentry·로그에서 최소한 아래를 본다.

- API 실패율·5xx, p95  
- **Connection reset / timeout** 건수  
- EC2 CPU·메모리, RDS CPU·IO, Redis 메모리·eviction  

개선 여부는 “감”이 아니라 위 지표와 `LOADTEST.md` 기록으로 판단한다.

---

## 8. 배포 공백 최소화 — 준무중단 (5순위, 단일 서버)

**현실:** 단일 EC2에서 **100% 무중단**은 보장하기 어렵고, **준무중단**이 목표다.

**방식:** Blue/Green **by Port**

- **Blue:** 기존 `web` → 호스트 `8000`  
- **Green:** 새 버전 컨테이너 → 호스트 `8001` (이미지·환경은 동일, 코드만 신규)  
- **Caddy:** `reverse_proxy` upstream을 `8000` ↔ `8001` 로 전환 후 reload  

**절차 요약:**

1. Green 기동·헬스체크 통과 (`/api/health/` 등)  
2. Caddy upstream을 Green으로 변경 → `caddy reload`  
3. 검증 후 Blue(구 버전) 중지  
4. 롤백: upstream을 다시 Blue로, Green 중지  

`docker-compose.yml`에 `web_green` 같은 별도 서비스(포트 `8001:8000`)를 두는 식으로 정리한다. RDS·Redis는 동일 호스트를 그대로 쓴다.

---

## 9. 이번 주 체크리스트 (통합)

- [ ] `docker-compose.yml`에 Gunicorn 안정화 옵션 반영 후 재기동  
- [ ] 동일 Locust 조건으로 `LOADTEST.md` 갱신  
- [ ] 느린 API 3개 `EXPLAIN ANALYZE` 및 조치  
- [ ] `.env`에 `LIST_API_CACHE_TTL` 조정(예: 120) 후 재측정  
- [ ] Celery `celery` / `embedding` 워커 분리 검토·적용  
- [ ] 배포: **중단 허용** vs **준무중단(Caddy)** 결정  

---

## 10. `LOADTEST.md` 기록 규칙

매 테스트마다 최소: **실패율**, **평균·p95**, **RPS**, **실패 원인 상위 3개**.

---

## 11. 보안·운영 주의

- `.env`에 비밀번호·API 키가 있으면 Git에 커밋하지 않는다.  
- 튜닝은 **한 번에 변수를 많이 바꾸지 말 것** — 원인 분리가 어려워진다.
