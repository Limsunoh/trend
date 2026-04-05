# AI_Trend 배포·운영 아키텍처 — draw.io용 **단독** 프롬프트

아래 **「복사용 블록」**만 통째로 복사해 draw.io의 AI/다이어그램 생성 입력란에 붙여 넣으세요.  
위쪽 설명은 사람용이며, AI는 **복사용 블록만** 보면 됩니다.

---

## 사람용 메모

- 복사 시 **Raw 텍스트**로 복사하면 줄바꿈이 유지됩니다.
- 이 저장소 기준: **CI = GitHub Actions**, 빌드된 이미지는 **Docker Hub**에 push, 서비스는 **단일 EC2**에서 Docker Compose로 운영, DB는 **RDS PostgreSQL**, 관측은 **CloudWatch + RDS Performance Insights / Database Insights + Sentry**를 쓴다는 전제를 블록 안에 적어 두었습니다.

---

## 「복사용 블록」— 여기부터 끝까지 복사

```
역할: 너는 draw.io 형식의 단일 아키텍처 다이어그램을 설계하는 도구다. 아래 조건을 전부 만족하는 다이어그램만 생성해라. 이 지시문 외의 이전 대화·외부 맥락은 없다고 가정한다.

프로젝트 이름: AI_Trend (실시간 트렌드 분석 대시보드, Django 백엔드 + React SPA).

이 다이어그램의 주제 (두 갈래, 둘 다 충분히 드러나게):
(1) 소스가 운영 서버에 도달하기까지의 경로: GitHub → GitHub Actions(CI) → Docker Hub(이미지) → 운영 EC2에서 pull·기동.
(2) 운영 중 무엇을 어디서 보는지: EC2·RDS용 Amazon CloudWatch(메트릭·로그·알람), RDS 부하는 Performance Insights 및 CloudWatch Database Insights(상위 SQL·AAS 등), 앱 오류는 Sentry.

이 다이어그램에서 반드시 하지 말 것:
- 마이크로서비스·ALB·ASG·ElastiCache 등 이 지시문에 없는 구성요소를 임의로 추가하지 마라.
- 웹·Celery·Redis를 각각 큰 박스로 펼쳐 “시스템 구조도”처럼 그리지 마라. 운영 서버 쪽은 아래 [구역 B]처럼 한 덩어리(또는 극소수 블록)로만 요약한다.
- 사용자 브라우저 → API까지의 요청 경로를 세밀하게 그리지 마라. 초점은 배포 파이프라인과 운영·관측이다.

다이어그램 제목(캔버스 상단): "AI_Trend — 배포·운영 아키텍처"
부제(선택): "GitHub Actions · Docker Hub · 운영 EC2 · CloudWatch / RDS Insights / Sentry"

레이아웃: 세 구역을 한 캔버스에 둔다. [구역 A] 배포 흐름이 위 또는 왼쪽에서 가장 먼저 읽히게 배치한다.

────────────────────────────────
[구역 A — 배포 파이프라인] (실선·직교 화살표로 순서 연결)
────────────────────────────────
1) 박스: GitHub 저장소 (main 등) — 개발자가 push/merge 하면 다음 단계로 이어진다고 표시.

2) 박스: GitHub Actions (CI/CD 워크플로)
   - 역할을 박스 안 또는 주석으로 구체적으로 적어라: 저장소 체크아웃 후 테스트·린트, Docker 이미지 빌드(Dockerfile 기준), 빌드 산출물을 Docker Hub로 push.
   - 라벨 예: "GitHub Actions", "test / lint / docker build / push".

3) 박스: Docker Hub
   - 의미: 빌드된 Docker 이미지가 저장되는 **원격 이미지 저장소**. "컨테이너 레지스트리" 같은 뜻만 적지 말고, **Docker Hub**라는 이름을 박스 제목에 넣어라.
   - (선택) 실제 이미지 이름을 알고 있다면 주석으로 예: limsunoh/trend 와 같이 적어도 된다.

4) 박스: 운영 EC2 인스턴스 (서비스가 실제로 실행되는 AWS EC2 한 대)
   - "프로덕션" 같은 모호한 단어만 쓰지 말고 **운영 EC2** 또는 **배포 대상 EC2**처럼 역할이 드러나게 적어라.
   - 배포 동작을 한 줄로: 운영자 또는 스크립트가 이 EC2에서 `docker compose pull` 후 `docker compose up -d` 등으로 최신 이미지를 받아 컨테이너를 재기동한다.
   - 비밀·환경 변수(.env 등)는 git에 없고 EC2 호스트(또는 별도 비밀 관리)에만 둔다는 점을 주석 한 줄로 적어도 된다.

5) (선택) 작은 박스: 배포 후 확인 — 예: HTTP GET /api/health/ 로 기동·헬스 확인.

구역 A 화살표 라벨 예: push → workflow, build & push image, pull on EC2, compose up, health check.

────────────────────────────────
[구역 B — 운영 서버 런타임 요약] (구역 A보다 시각적으로 작게, 한 덩어리)
────────────────────────────────
하나의 큰 박스 제목 예: "EC2 위 Docker Compose (서비스 실행)"
박스 **안 텍스트**로만 요약한다 (개별 컨테이너·포트 나열은 최소화):
- Gunicorn 웹, Celery worker·beat, Redis, Chroma용 공유 볼륨 등이 Compose로 함께 올라간다는 수준.
- PostgreSQL은 이 EC2 디스크가 아니라 **Amazon RDS(PostgreSQL)** 에 두고 앱이 연결한다는 점을 한 줄.
- (선택) Caddy가 TLS 종료 후 내부 웹으로 넘긴다면 주석 한 줄.

────────────────────────────────
[구역 C — 운영·관측] (넓은 면적, 점선 위주로 연결)
────────────────────────────────
1) Amazon CloudWatch — EC2·RDS와 연동되는 관측·알람 허브로 그려라. 하위 또는 주석으로 구체화해라:
   - EC2 관련: CPU 사용률(CPUUtilization), 메모리(에이전트/지표로 수집되는 경우), 네트워크 입·출력(NetworkIn/NetworkOut), 디스크·EBS, StatusCheckFailed 등 **실제로 쓰는 지표 유형**을 예시로 나열.
   - (선택) CloudWatch Logs: 로그 그룹·스트림, 애플리케이션/시스템 로그 수집.
   - 알람: 메트릭 임계값 초과 시 알림(SNS 등으로 운영자에게 전달 가능).

2) RDS 모니터링 + Insights (DB 부하·쿼리 분석)
   - **Performance Insights(PI)**: RDS에서 활성화한 부하 분석. 상위 SQL(Top SQL), Average Active Sessions(AAS), 대기 이벤트 등 **쿼리·세션 중심** 분석을 이 박스 또는 연결 라벨에 적어라.
   - **CloudWatch Database Insights**: AWS 콘솔(CloudWatch)에서 RDS 부하를 보는 화면; PI와 연계해 AAS·Top SQL 등을 볼 수 있다는 관계를 점선 또는 주석으로 표시.
   - RDS ↔ CloudWatch: DB 인스턴스 메트릭·PI 데이터가 CloudWatch와 연동된다는 수준의 연결(점선, 라벨 예: metrics, PI).

3) Sentry
   - 애플리케이션 예외·성능 트레이스(SDK → Sentry SaaS). 운영 서버(구역 B 박스)에서 Sentry로 점선, 라벨 errors / traces.

4) (선택) 알람 → 운영자: CloudWatch 알람 → 이메일/Slack 등.

구역 C 라벨은 짧게 유지하되, 박스 안 설명 문장으로 위 항목이 빠지지 않게 해라.

선 종류:
- 실선: GitHub → GitHub Actions → Docker Hub → 운영 EC2 배포 단계, (선택) 헬스체크. 운영 서버 요약 박스 → RDS "앱이 DB 사용" 한 줄.
- 점선: EC2·RDS·앱 → CloudWatch, RDS·PI·Database Insights 관계, 앱 → Sentry, 알람 → 운영자.

시각 스타일:
- 직교(orthogonal) 위주, 곡선 최소.
- 배포 체인(구역 A)은 실선을 굵게·한눈에.
- 관측(구역 C)은 점선 + (선택) 배경색으로 구역 A와 구분.

다이어그램 하단 각주 블록:
- GitHub Actions가 이미지를 빌드해 Docker Hub에 push하고, 운영 EC2는 pull 후 Docker Compose로 기동한다.
- .env 등 비밀은 git에 넣지 않는다.
- CloudWatch: EC2·RDS 메트릭, (선택) 로그, 알람.
- Performance Insights: RDS 부하·상위 SQL·AAS 등 분석.
- Database Insights: CloudWatch에서 DB 부하를 보는 화면(PI와 연계).
- Sentry: 앱 레벨 오류·트레이스.

출력: 위 조건을 만족하는 draw.io 다이어그램(또는 동일 내용의 박스·화살표 목록). 한국어 라벨 사용 가능.
```

## 「복사용 블록」— 여기까지 복사

---

## 블록 밖에서 바꿀 수 있는 값 (선택)

- Docker Hub **이미지 이름·태그**를 구역 A의 Docker Hub 박스 주석에 적을 수 있습니다.
- GitHub Actions 워크플로 파일명(예: `.github/workflows/xxx.yml`)을 CI 박스에 적어도 됩니다.
