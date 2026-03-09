# Locust 부하 테스트

대용량 트래픽을 시뮬레이션하고 CloudWatch·Sentry·로그와 함께 관찰하기 위한 가이드.

## 1. 설치 (로컬 PC, 서버와 다른 머신 권장)

```bash
pip install locust
```

프로젝트 가상환경에 넣거나, 별도 venv 사용 가능.

## 2. 실행

프로젝트 루트에서:

```bash
# EC2 서버 대상 (기본)
locust -f locustfile.py --host=http://3.37.203.226:8000

# 웹 UI 포트 변경 (기본 8089)
locust -f locustfile.py --host=http://3.37.203.226:8000 --web-port=8090

# 헤드리스 (UI 없이, 터미널만)
locust -f locustfile.py --host=http://3.37.203.226:8000 --headless -u 20 -r 5 -t 60
# -u 20: 동시 사용자 20명
# -r 5: 초당 5명씩 증가
# -t 60: 60초 동안 실행
```

## 3. 웹 UI 사용

1. `locust` 실행 후 브라우저에서 **http://localhost:8089** 접속.
2. **Number of users**: 동시 가상 사용자 수 (예: 50).
3. **Ramp up**: 초당 몇 명씩 증가시킬지 (예: 5).
4. **Start swarming** 클릭.
5. **Statistics** 탭에서 RPS, 응답 시간(평균/백분위), 실패 수 확인.

## 4. 테스트 대상 API (locustfile.py)

| 비중 | 엔드포인트 | 설명 |
|------|------------|------|
| 10 | GET /api/health/ | 헬스 체크 |
| 8 | GET /api/dashboard/news/ | 뉴스 목록 |
| 8 | GET /api/dashboard/social/ | 소셜 목록 |
| 5 | GET /api/analyzer/analysis-results/ | 분석 결과 목록 |
| 3 | GET /api/analyzer/analysis/keywords/ | 키워드 분석 |
| 2 | GET /api/user_qa/history/ | QA 히스토리 |
| 1 | POST /api/user_qa/query/ | QA 질의 (부하 큼) |

비중은 상대 비율. POST /api/user_qa/query/ 는 CSRF 때문에 403이 나면, 테스트용으로 해당 출처를 `CSRF_TRUSTED_ORIGINS`에 넣거나 일시적으로 제외할 수 있음.

## 5. 부하 테스트 시 확인할 것

- **Locust UI**: RPS, 응답 시간, 실패율.
- **AWS CloudWatch**: EC2 CPU, 메모리, 네트워크.
- **Sentry**: 에러/예외 발생 여부.
- **서버 로그**: `docker compose logs -f web`, `tail -f logs/access.log`, `logs/error.log`.

## 6. 주의

- Locust는 **서버(EC2)가 아닌 로컬 PC**에서 실행하는 것을 권장 (같은 서버에서 돌리면 부하 생성이 서버 지표를 왜곡함).
- EC2 보안 그룹에서 **8000 포트**가 Locust를 실행하는 PC IP(또는 0.0.0.0)에 열려 있어야 함.
