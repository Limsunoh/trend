# 실시간 트렌드 분석 대시보드

뉴스(RSS)와 소셜 미디어 데이터를 수집하고, 키워드·트렌드 분석 결과를 React 기반 대시보드에서 확인하는 풀스택 프로젝트입니다.

---

## 주요 기능

- RSS 기반 소스 등록 및 수집 트리거·잡(job) 관리(Celery 백그라운드·작업 큐)
- 분석 결과 API(키워드, 급상승, 시간차, 플랫폼 비교, 트렌드 동기화, 시간대별, 참여도 등)
- 뉴스 기사·소셜 게시물 목록·상세 API 및 React SPA
- Redis 캐시로 목록·집계 API 성능 최적화
- 부하 테스트를 바탕으로 한 캐시·큐·동시성 튜닝 경험
- Swagger/OpenAPI, `GET /api/health/`, `GET /api/debug/active-requests/`

---

## 기술 스택

| 영역 | 기술 |
|------|------|
| Backend | Django 4.2, Django REST Framework, drf-spectacular |
| 데이터·캐시 | PostgreSQL, Redis |
| 작업 큐·백그라운드 | Celery |
| 수집·크롤링 | dcinside-read-api(dcapi), Feedparser, requests, Selenium, BeautifulSoup4 |
| 분석·NLP | PyKomoran(KoNLPy), Chroma(벡터 검색) |
| Frontend | React 18, Vite, React Router, Axios |
| 운영 | Gunicorn + gevent |

---

## 프로젝트 구조

| 경로 | 역할 |
|------|------|
| `trend_analyzer/` | Django 설정, URL 라우팅, Swagger·health |
| `data_collector/` | 소스 등록, 수집 트리거·잡 API |
| `dashboard/` | 뉴스·소셜 목록·상세 API |
| `analyzer/` | 분석 타입별 결과 API |
| `user_qa/` | RAG 질의·히스토리·변환 API |
| `common/` | health, active requests, SPA 서빙 |
| `frontend/` | React SPA |

---

## 아키텍처

### 시스템 아키텍처

인프라·런타임 구성(EC2, Docker Compose, RDS, Redis, Celery, Chroma 등)과 데이터 흐름

![시스템 아키텍처](docs/AI_Trend%20%EC%8B%9C%EC%8A%A4%ED%85%9C%20%EC%95%84%ED%82%A4%ED%85%8D%EC%B2%98.png)

### 애플리케이션 아키텍처

Django 앱·프론트·외부 연동 중심의 논리 구조

![애플리케이션 아키텍처](docs/AI_Trend%20%EC%95%A0%ED%94%8C%EB%A6%AC%EC%BC%80%EC%9D%B4%EC%85%98%20%EC%95%84%ED%82%A4%ED%85%8D%EC%B2%98.png)

### 배포·운영 아키텍처

GitHub Actions → Docker Hub → 운영 EC2, CloudWatch·RDS Insights·Sentry 등 관측

![배포·운영 아키텍처](docs/AI_Trend%20%EB%B0%B0%ED%8F%AC%C2%B7%EC%9A%B4%EC%98%81%EC%95%84%ED%82%A4%ED%85%8D%EC%B2%98-icon.png)

### 기타 문서

| 이름 | 설명 |
|------|------|
| [ERD](docs/AI_Trend-ERD.png) | PostgreSQL 기준 엔티티 관계(주요 테이블·관계) |

---

## Live Demo

| 항목 | URL |
|------|-----|
| 서비스 | https://aitrend.xn--hu5b25b77nvwc.xn--3e0b707e/ |
| Swagger UI | https://aitrend.xn--hu5b25b77nvwc.xn--3e0b707e/api/docs/ |
| ReDoc | https://aitrend.xn--hu5b25b77nvwc.xn--3e0b707e/api/redoc/ |

---

## 주요 API Prefix

| Prefix | 설명 |
|--------|------|
| `/api/collector/` | 소스, 수집 트리거, 잡 상태 |
| `/api/dashboard/` | 뉴스·소셜 목록·상세 |
| `/api/analyzer/` | 분석 결과(타입별) |
| `/api/user_qa/` | RAG 기반 질의 |
