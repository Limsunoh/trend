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
| 목록 TTL | `.env` 그룹별: `LIST_API_CACHE_TTL_DASHBOARD`(기본 120s), `LIST_API_CACHE_TTL_ANALYZER`(기본 600s), `LIST_API_CACHE_TTL_QA_HISTORY`(기본 60s). `LIST_API_CACHE_TTL`만 설정 시 세 그룹 동일 값(하위 호환) |
| Celery | 단일 `celery_worker`, `-Q celery,embedding` 혼합 (`--pool=solo`) |

---

## 2. 실행 우선순위 (이 순서 권장)

1. **연결 안정성** — Gunicorn 옵션 + OS/프록시 한도 점검 (실패율 0%에 가깝게)
2. **DB** — 느린 API 위주 `EXPLAIN ANALYZE`, 인덱스·N+1·직렬화
3. **캐시 TTL** — `.env`에서 `LIST_API_CACHE_TTL_DASHBOARD` / `LIST_API_CACHE_TTL_ANALYZER` / `LIST_API_CACHE_TTL_QA_HISTORY` 조정 (또는 통일 시 `LIST_API_CACHE_TTL`만)
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

### 3-1. 스파이크 구간 해결 (추가 실행 절차)

**목적:** 1~2분 구간의 p95 급등(예: 10~13초)과 RPS 급락을 줄인다.

1. **시각 정렬부터 고정**  
   Locust 스파이크 시각(UTC)과 CloudWatch 1분 메트릭(EC2 CPU, CWAgent 메모리, RDS CPU/IOPS), `web-access` 로그 시각을 같은 UTC 기준으로 맞춘다.

2. **원인 분리 규칙(한 번에 1개만 변경)**  
   아래는 동시에 바꾸지 않는다.  
   - Gunicorn: `--max-requests`, `--max-requests-jitter`, `--worker-connections`, `--keep-alive`  
   - 캐시: `LIST_API_CACHE_TTL_*` (또는 통일 `LIST_API_CACHE_TTL`)  
   - 백그라운드 작업: Celery 큐/워커 분리 여부  
   각 변경 후 동일 Locust 조건으로 재측정한다.

3. **1차 튜닝 순서(권장)**  
   - `max-requests` 완화: `10000 -> 20000` (재시작 빈도 완화)  
   - `max-requests-jitter` 확대: `1000 -> 3000` (재시작 시점 분산 강화)  
   - `worker-connections` 점검: 500 유지 후, 실패율/지연이 나쁘면 300~400도 비교  
   변경 후 Failure%, p95, p99, RPS를 같은 길이 테스트(3분)로 비교한다.

4. **캐시 미스 버스트 완화**  
   스파이크 시점에 ReadIOPS가 동반 상승하면 캐시 미스 가능성이 높다.  
   `.env`의 그룹별 TTL(예: `LIST_API_CACHE_TTL_DASHBOARD`)을 단계적으로 조정하고, 데이터 신선도와 p95를 함께 본다.

5. **호스트 자원 경쟁 제거**  
   스파이크 시각에 Celery/임베딩이 겹치면 웹 요청과 CPU 경쟁이 생긴다.  
   가능하면 테스트 시간에는 임베딩 큐를 분리하거나 동시 실행을 피해서 웹 API 성능만 먼저 안정화한다.

6. **완료 기준(스파이크 해결 판정)**  
   - Failure%: 0% 유지  
   - 스파이크 구간 p95: 기존 대비 30% 이상 감소  
   - 같은 동시 사용자에서 RPS 급락 폭 축소  
   - CloudWatch에서 CPU 99% 구간 지속 시간이 단축

---

## 3-3. CPU 사용량은 낮추고 RPS는 높이는 방법 (단일 EC2 실전판)

**핵심 원칙:** "같은 요청을 더 싸게 처리"하면 CPU가 내려가고 RPS가 오른다.  
아래는 효과가 큰 순서대로 적용한다.

1. **캐시 히트율 먼저 올리기 (가장 즉효)**  
   - 대상: `dashboard/news`, `dashboard/social`, `analysis-results`, `keywords`, `history`
   - **CPU·RPS 관점:** 같은 트래픽에서 **TTL을 짧게 줄이면** 캐시 미스가 늘어 DB·직렬화가 자주 돌고 **웹 CPU는 보통 올라간다**. **히트율을 올려 CPU를 내리려면** (데이터가 허용하는 한) TTL을 **길게** 잡는 쪽이 맞다.  
   - **그룹 3개 변수의 의미:** `LIST_API_CACHE_TTL_DASHBOARD` / `LIST_API_CACHE_TTL_ANALYZER` / `LIST_API_CACHE_TTL_QA_HISTORY`는 **엔드포인트별로 stale를 얼마나 허용할지** 나누기 위한 것이다. 관례적으로 수집(뉴스·소셜)은 갱신이 잦아 **상대적으로 짧게**, 분석 목록은 **상대적으로 길게**, QA 히스토리는 최신 대화 반영을 위해 **더 짧게** 두는 식으로 **비율**을 맞출 뿐, “짧을수록 CPU가 내려간다”는 뜻이 아니다.  
   - **방법:** 신선도 요구와 p95·CPU를 같이 보며 `.env` 값을 조정하고, **한 번에 한 변수(또는 한 그룹)** 만 바꾼 뒤 동일 부하로 재측정한다. 통일 롤백이 필요하면 `LIST_API_CACHE_TTL`만 설정(하위 호환).  
   - 기대 효과: 히트가 늘면 DB 조회·직렬화·JSON 생성이 줄어 **평균 CPU 감소·RPS 여력 상승**

2. **목록 응답 크기 줄이기 (직렬화 CPU 절감)**  
   - 방법: 목록 API는 경량 필드만 반환, 상세(`retrieve`)에서만 무거운 필드 반환 (`get_serializer_class()` 패턴 등).  
   - 방법: `page_size`·`max_page_size`로 **한 응답의 상한**을 두기(큰 페이지는 요청당 직렬화·전송 비용이 커짐).  
   - 기대 효과: Python 직렬화·응답 전송 비용 감소 → 동일 CPU로 더 많은 요청 처리. (Redis 목록 캐시 히트 시에도 캐시에 넣는/꺼내는 페이로드가 작을수록 유리.)

3. **N+1/비효율 쿼리 제거 (앱 CPU + DB 왕복 동시 절감)**  
   - 방법: `select_related`/`prefetch_related`, 불필요 정렬·조건 제거.  
   - 방법: 상위 느린 API 몇 개만 골라 PostgreSQL이면 `EXPLAIN (ANALYZE, BUFFERS)` 등으로 반복 확인(다른 DB면 해당 DB의 실행 계획 도구).  
   - 기대 효과: 요청당 처리 시간 단축 → RPS 여력 상승, CPU 스파이크 완화.

4. **Gunicorn 워커 재시작 정책 (`--max-requests`)**  
   - **필수 아님.** 이 옵션은 주로 **장기 실행 워커의 메모리 누수·팽창 완화**용이다. 부하 특성상 **재시작 순간에만 p95·RPS가 크게 튄다면 제거해도 된다** (우리 케이스에서도 제거 후 스파이크 완화 사례 있음).  
   - **제거 시 대신 할 일:** 배포·롤링 재시작으로 주기적 갱신, EC2/CWAgent **메모리 추이·OOM 알람**으로 누수 감시.  
   - **유지할 때:** 값을 **매우 크게** 잡거나 `max-requests-jitter`로 재시작 시각을 흩어 **스파이크 완화**를 노린다.  
   - 한 번에 하나만 바꾼 뒤 동일 부하로 재측정한다.

5. **웹과 백그라운드 CPU 경쟁 줄이기**  
   - 방법: 부하 테스트 구간에서 `embedding` 큐 부하를 줄이거나 호스트를 분리해 **웹과 동시에 CPU를 쓰지 않게** 한다.  
   - 방법: `settings.py`의 `celery`/`embedding` 큐 분리·라우팅 유지.  
   - 기대 효과: 웹 워커가 쓸 CPU 시간 확보 → p95·RPS 안정화.

6. **부하 도구 해석 주의 (서버 병목 오판 방지)**  
   - **k6** (`k6_trend_api.js`): `dropped_iterations`가 크면 **타깃 서버 한계**와 **부하 생성기(실행 PC) 한계**가 섞일 수 있다. `Insufficient VUs`면 `PRE_VUS`·`MAX_VUS`를 올려 생성기 쪽 여력부터 맞춘다.  
   - **Locust**: RPS·실패가 한계면 **Locust 실행 머신의 CPU/네트워크**와 `--workers`(분산) 여부를 함께 본다. UI에 실패가 거의 없는데 서버만 바쁘다면 생성기 병목은 아닐 가능성이 크다.

### 3-3 적용 체크리스트 (변경 1개씩)

- [ ] 캐시 TTL·히트율(신선도 한도 내) 조정 → 동일 시나리오 3분 재측정  
- [ ] 목록 응답 필드/페이지 크기 조정 -> 재측정  
- [ ] 느린 API 3개 쿼리 최적화 -> 재측정  
- [ ] Gunicorn 재시작 관련 옵션 1개 조정 -> 재측정  
- [ ] Celery 경쟁 제거(또는 분리) -> 재측정

### 3-3 완료 판정

- Failure%: 0% 유지  
- 동일 부하에서 평균 CPU 하락  
- 동일 부하에서 RPS 상승  
- p95/p99가 이전 대비 개선(스파이크 구간 포함)

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

**현재 코드:** `.env`에 `LIST_API_CACHE_TTL`만 있으면 세 그룹 동일 TTL. 없으면 기본값은 대시보드 **120초**, 분석 **600초**, QA 히스토리 **60초** (`trend_analyzer/settings.py`).  
`common/list_cache.py`의 `get_list_cache_ttl(prefix)`가 prefix별로 위 설정을 고른다.

**1차 운영 권장 (단일 인스턴스):** `.env`에 그룹별 TTL을 두고, stale·DB 부하·p95를 보며 조정. 통일 롤백이 필요하면 `LIST_API_CACHE_TTL`만 설정.

**엔드포인트 그룹:** 뉴스/소셜 → `LIST_API_CACHE_TTL_DASHBOARD`, `analysis-results`·`analysis/*` 목록 → `LIST_API_CACHE_TTL_ANALYZER`, `user_qa/history` → `LIST_API_CACHE_TTL_QA_HISTORY`.

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
- [ ] `.env`에 `LIST_API_CACHE_TTL_DASHBOARD` / `LIST_API_CACHE_TTL_ANALYZER` / `LIST_API_CACHE_TTL_QA_HISTORY` 조정 후 재측정  
- [ ] Celery `celery` / `embedding` 워커 분리 검토·적용  
- [ ] 배포: **중단 허용** vs **준무중단(Caddy)** 결정  

---

## 10. `LOADTEST.md` 기록 규칙

매 테스트마다 최소: **실패율**, **평균·p95**, **RPS**, **실패 원인 상위 3개**.

---

## 11. 보안·운영 주의

- `.env`에 비밀번호·API 키가 있으면 Git에 커밋하지 않는다.  
- 튜닝은 **한 번에 변수를 많이 바꾸지 말 것** — 원인 분리가 어려워진다.
