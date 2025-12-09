# 실시간 인기/트렌드 분석 대시보드

## 주요 기능 (예정)
- 뉴스 및 소셜 미디어 데이터 수집 자동화
- 키워드/토픽 분석과 통계 집계
- 실시간 트렌드 대시보드 제공
- RAG 기반 질의응답 시스템

## 기술 스택 (예정)
- Backend: Django, Django REST Framework
- Task Queue: Celery, Redis
- Data Processing: Pandas, scikit-learn, NLTK, KoNLPy
- Data Collection: BeautifulSoup4, Selenium, Tweepy, Feedparser
- RAG & Vector DB: ChromaDB, LangChain, Sentence Transformers, OpenAI
- Visualization: Plotly, Dash
- Infrastructure: AWS S3 (선택 사항)

## 사용 방법

### 1. NewsSource 수집

뉴스 소스(경향신문, 중앙일보 등)를 CSV 파일에서 로드합니다.

```bash
# 가상환경 활성화
source .venv/Scripts/activate  # Windows Git Bash
# 또는
.venv\Scripts\activate  # Windows CMD

# NewsSource 수집
python manage.py load_csv_sources
```

**참고:**
- 기본 CSV 파일: `NewsSource_RSS.csv`
- 다른 파일 사용: `python manage.py load_csv_sources --csv-file 경로/파일명.csv`

### 2. NewsArticle 수집

RSS 피드에서 뉴스 기사를 수집합니다.

#### 2-1. 서버 실행

```bash
# 가상환경 활성화
source .venv/Scripts/activate

# Django 서버 실행
python manage.py runserver
```

#### 2-2. Celery 워커 실행

새 터미널 창에서:

```bash
# 가상환경 활성화
source .venv/Scripts/activate

# Celery 워커 실행 (Windows)
celery -A trend_analyzer worker --pool=solo --loglevel=info
```

#### 2-2-1. Flower로 Celery 모니터링 (선택사항)

Celery 작업을 웹 브라우저에서 모니터링할 수 있습니다.

**설치:**
```bash
pip install flower
```

**실행:**
```bash
# 가상환경 활성화
source .venv/Scripts/activate

# Flower 실행 (로컬 Redis 사용)
celery -A trend_analyzer flower

# 원격 Redis 사용
celery -A trend_analyzer flower --broker=redis://121.148.185.46:6379/0

# 포트 변경 (기본값: 5555)
celery -A trend_analyzer flower --port=5555
```

**웹 브라우저에서 접속:**
```
http://localhost:5555
```

**Flower에서 확인할 수 있는 정보:**
- **Tasks**: 실행 중/완료/실패한 작업 목록 및 상세 정보
- **Workers**: 연결된 Celery worker 상태
- **Monitor**: 실시간 작업 모니터링
- **Broker**: Redis 연결 상태
- **API**: REST API 엔드포인트

#### 2-3. API로 수집 시작

**방법: Swagger UI 사용**

1. 브라우저에서 `http://localhost:8000/api/docs/` 접속
2. `/api/collector/trigger/` 엔드포인트 찾기
3. POST 요청 실행:
   - **전체 소스 수집**: `{"collect_all": true}`
   - **특정 소스 수집**: `{"source_id": 1}` 또는 `{"source_name": "경향신문"}`

```

**수집 상태 확인:**

1. **Celery 워커 터미널 로그 확인**
   - 작업이 실행 중이면: `[INFO] Task ... received`, `[INFO] RSS 피드 수집 시작` 등의 로그가 계속 출력됨
   - 작업이 완료되면: `[INFO] Task ... succeeded` 메시지 출력
   - **모든 작업 완료 확인**: 마지막 작업의 `succeeded` 메시지 후 새로운 로그가 멈추면 완료

2. **Celery 명령어로 확인** (새 터미널에서)
   ```bash
   # 가상환경 활성화
   source .venv/Scripts/activate
   
   # 실행 중인 작업 확인
   celery -A trend_analyzer inspect active
   # 결과: `- empty -` 이면 모든 작업 완료
   ```

3. **Swagger/API로 확인**
   - Swagger: `/api/collector/jobs/` (GET) - 최근 수집 작업 목록 및 상태 확인
   - 각 작업의 `status` 필드: `completed` (완료), `running` (실행 중), `failed` (실패)

### 3. 실패한 RSS 피드 소스 정리

수집 작업 후 RSS 피드가 작동하지 않는 NewsSource를 찾아 삭제/비활성화합니다.

```bash
# 가상환경 활성화
source .venv/Scripts/activate

# 테스트 모드 (삭제하지 않고 확인만)
python manage.py remove_failed_sources --test

# 실제 삭제
python manage.py remove_failed_sources --confirm

# 삭제 대신 비활성화
python manage.py remove_failed_sources --confirm --deactivate

# 최근 N일간의 작업 확인 (기본값: 1일)
python manage.py remove_failed_sources --test --days 7
```

**판단 기준:**
- 최근 수집 작업에서 RSS 피드 파싱 오류가 발생한 소스
- 최근 수집 작업에서 네트워크 오류가 발생한 소스
- 최근 수집 작업에서 기사가 0개였고 RSS 피드 테스트도 실패한 소스
