# 실시간 트렌드 분석 대시보드

뉴스·소셜 미디어 데이터를 수집하고, 키워드·트렌드 분석 결과를 대시보드에서 확인할 수 있는 풀스택 프로젝트입니다.

---

## 목차

- [주요 기능](#주요-기능)
- [기술 스택](#기술-스택)
- [프로젝트 구조](#프로젝트-구조)
- [시작하기](#시작하기)
- [사용 방법](#사용-방법)
- [API 문서](#api-문서)
- [문서](#문서)

---

## 주요 기능

| 구분 | 설명 |
|------|------|
| **데이터 수집** | RSS 기반 뉴스 기사 수집, 소셜 미디어 게시물 수집 (Celery 비동기) |
| **대시보드** | 뉴스/소셜 목록 조회, 검색·정렬·페이지네이션, 상세 페이지 |
| **트렌드 분석** | 11종 분석(키워드, 플랫폼 비교, 인기/급상승 키워드, 시간차, 동기화, 시간대별, 타임라인, 참여도 등) |
| **분석 결과** | 분석 타입별 목록 조회, 상세 결과(summary/result_data) 확인 |

---

## 기술 스택

| 영역 | 기술 |
|------|------|
| **Backend** | Django 4.2, Django REST Framework |
| **DB** | PostgreSQL, Redis |
| **Task Queue** | Celery, Flower(모니터링) |
| **Frontend** | React 18, Vite, React Router, Axios |
| **분석/ML** | PyKomoran(KoNLPy), Pandas, scikit-learn |
| **수집** | Feedparser, BeautifulSoup4, Selenium, Tweepy |
| **API 문서** | drf-spectacular (Swagger/ReDoc) |

---

## 프로젝트 구조

```
trend/
├── trend_analyzer/     # Django 프로젝트 설정
├── dashboard/          # 대시보드 API (뉴스/소셜 목록)
├── data_collector/     # 뉴스·소셜 수집, 소스 관리
├── analyzer/          # 트렌드 분석 로직·API·Celery 태스크
├── user_qa/            # (추가 모듈)
├── frontend/           # React + Vite 프론트엔드
│   └── src/
│       ├── components/ # Dashboard, DataCollector, Analyzer, 상세 페이지
│       └── services/   # API 클라이언트
├── manage.py
└── requirements.txt
```

---

## 시작하기

### 요구 사항

- Python 3.10+
- Node.js 18+ (프론트엔드)
- PostgreSQL, Redis

### 설치

```bash
# 저장소 클론 후
cd trend

# 가상환경 생성 및 활성화
python -m venv .venv
source .venv/Scripts/activate   # Windows Git Bash
# .venv\Scripts\activate        # Windows CMD

# 의존성 설치
pip install -r requirements.txt

# 환경 변수 설정 (필수)
# .env 파일을 생성하고 DB, Redis, SECRET_KEY 등 설정 (실행 방법은 .env 하단 참고)
```

### 프론트엔드

```bash
cd frontend
npm install
npm run dev
```

**서버 실행, Celery 워커, Flower, 분석 명령어** 등 상세 실행 방법은 **`.env` 파일 맨 아래**에 정리되어 있습니다. (`.env`는 git에 포함되지 않습니다.)

---

## 사용 방법

### 1. 뉴스 소스 로드

CSV에서 뉴스 소스(예: 경향신문, 중앙일보)를 DB에 로드합니다.

```bash
python manage.py load_csv_sources
# 다른 CSV: python manage.py load_csv_sources --csv-file 경로/파일명.csv
```

### 2. 뉴스·소셜 수집

1. Django 서버와 Celery 워커를 실행합니다. (명령어는 `.env` 하단 참고)
2. **Swagger** `http://localhost:8000/api/docs/` 에서 `POST /api/collector/trigger/` 호출  
   - 전체: `{"collect_all": true}`  
   - 특정 소스: `{"source_id": 1}` 또는 `{"source_name": "경향신문"}`
3. 수집 상태는 Celery 로그 또는 `GET /api/collector/jobs/` 로 확인합니다.

### 3. 실패한 RSS 소스 정리

```bash
python manage.py remove_failed_sources --test    # 확인만
python manage.py remove_failed_sources --confirm # 삭제
python manage.py remove_failed_sources --confirm --deactivate  # 비활성화
```

### 4. 트렌드 분석

- **전체 분석 일괄 실행:** `python manage.py run_all_analyses` (옵션은 `.env` 참고)
- **대시보드**에서 “분석 결과” 탭으로 이동 후, 분석 타입별 목록·상세 결과를 확인할 수 있습니다.

---

## API 문서

| 문서 | URL |
|------|-----|
| Swagger UI | http://localhost:8000/api/docs/ |
| ReDoc | http://localhost:8000/api/redoc/ |

주요 API prefix:

- `/api/dashboard/` — 뉴스·소셜 목록 (대시보드용)
- `/api/collector/` — 수집 트리거, 소스, 작업 목록
- `/api/analyzer/` — 분석 결과 목록·상세, 분석 타입별 엔드포인트

---

## 문서

- [트러블슈팅 가이드](TROUBLESHOOTING.md) — 개발 중 발생한 문제와 해결 방법

---

*실행 명령(서버, Celery, Flower, 프론트엔드, 분석 명령 등)은 `.env` 파일 하단에만 정리되어 있으며, git에는 포함되지 않습니다.*
