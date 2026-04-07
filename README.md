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

## 🖥️ 기술 스택 (Technologies & Tools)

[Shields.io](https://shields.io) 배지 · [Project_SANA_I](https://github.com/Limsunoh/Project_SANA_I?tab=readme-ov-file) README와 같은 `for-the-badge` 스타일

### 📝 FrontEnd

[![React 18](https://img.shields.io/badge/React_18-20232A?style=for-the-badge&logo=react&logoColor=61DAFB)](https://react.dev/)
[![Vite](https://img.shields.io/badge/Vite-646CFF?style=for-the-badge&logo=vite&logoColor=white)](https://vitejs.dev/)
[![React Router](https://img.shields.io/badge/React_Router-CA4245?style=for-the-badge&logo=reactrouter&logoColor=white)](https://reactrouter.com/)
[![Axios](https://img.shields.io/badge/Axios-5A29E4?style=for-the-badge&logo=axios&logoColor=white)](https://axios-http.com/)

### 📝 BackEnd

[![Python 3.10+](https://img.shields.io/badge/Python_3.10+-3776AB?style=for-the-badge&logo=python&logoColor=white)](https://www.python.org/)
[![Django 4.2](https://img.shields.io/badge/Django_4.2-092E20?style=for-the-badge&logo=django&logoColor=white)](https://www.djangoproject.com/)
[![Django REST Framework](https://img.shields.io/badge/Django_REST_Framework-092E20?style=for-the-badge&logo=django&logoColor=white)](https://www.django-rest-framework.org/)
[![drf-spectacular](https://img.shields.io/badge/drf--spectacular-6BA539?style=for-the-badge&logo=openapiinitiative&logoColor=white)](https://drf-spectacular.readthedocs.io/)

### 📝 Data · Cache

[![PostgreSQL](https://img.shields.io/badge/PostgreSQL-316192?style=for-the-badge&logo=postgresql&logoColor=white)](https://www.postgresql.org/)
[![Amazon RDS](https://img.shields.io/badge/Amazon_RDS-527FFF?style=for-the-badge&logo=amazonrds&logoColor=white)](https://aws.amazon.com/rds/)
[![Redis](https://img.shields.io/badge/Redis-DC382D?style=for-the-badge&logo=redis&logoColor=white)](https://redis.io/)

### 📝 Queue · 수집 · 크롤링

[![Celery](https://img.shields.io/badge/Celery-37814A?style=for-the-badge&logo=celery&logoColor=white)](https://docs.celeryq.dev/)
[![dcinside-read-api](https://img.shields.io/badge/dcinside--read--api-181717?style=for-the-badge&logo=github&logoColor=white)](https://github.com/Limsunoh/dcinside-read-api)
[![requests](https://img.shields.io/badge/requests-3776AB?style=for-the-badge&logo=python&logoColor=white)](https://requests.readthedocs.io/)
[![Selenium](https://img.shields.io/badge/Selenium-43B02A?style=for-the-badge&logo=selenium&logoColor=white)](https://www.selenium.dev/)
[![BeautifulSoup4](https://img.shields.io/badge/BeautifulSoup4-9400d3?style=for-the-badge)](https://www.crummy.com/software/BeautifulSoup/)
[![Feedparser](https://img.shields.io/badge/Feedparser-FF6600?style=for-the-badge&logo=rss&logoColor=white)](https://feedparser.readthedocs.io/)

### 📝 분석 · NLP

[![KoNLPy PyKomoran](https://img.shields.io/badge/KoNLPy_PyKomoran-3776AB?style=for-the-badge&logo=python&logoColor=white)](https://konlpy.org/)
[![Chroma](https://img.shields.io/badge/Chroma_vector_DB-FF6B35?style=for-the-badge)](https://www.trychroma.com/)

### 📝 운영 · Infra

[![Gunicorn](https://img.shields.io/badge/Gunicorn-499848?style=for-the-badge&logo=gunicorn&logoColor=white)](https://gunicorn.org/)
[![gevent](https://img.shields.io/badge/gevent-2E8B57?style=for-the-badge)](http://www.gevent.org/)
[![Docker](https://img.shields.io/badge/Docker-2496ED?style=for-the-badge&logo=docker&logoColor=white)](https://www.docker.com/)
[![Amazon EC2](https://img.shields.io/badge/Amazon_EC2-FF9900?style=for-the-badge&logo=amazonec2&logoColor=white)](https://aws.amazon.com/ec2/)

### 💬 문서 · 협업

[![API 명세 Notion](https://img.shields.io/badge/API_명세_(Notion)-000000?style=for-the-badge&logo=notion&logoColor=white)](https://plum-erigeron-514.notion.site/AI_Trend_API-33b4933e7f1c81198bd5cabc650560e6)
[![Limsunoh](https://img.shields.io/badge/Limsunoh-181717?style=for-the-badge&logo=github&logoColor=white)](https://github.com/Limsunoh)
[![kwang1215](https://img.shields.io/badge/kwang1215-181717?style=for-the-badge&logo=github&logoColor=white)](https://github.com/kwang1215)

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

![배포·운영 아키텍처](docs/AI_Trend%20%EB%B0%B0%ED%8F%AC%C2%B7%EC%9A%B4%EC%98%81%20%EC%95%84%ED%82%A4%ED%85%8D%EC%B2%98.png)

### 기타 문서

| 이름 | 설명 |
|------|------|
| [API 명세 (Notion)](https://plum-erigeron-514.notion.site/AI_Trend_API-33b4933e7f1c81198bd5cabc650560e6) | 엔드포인트·request/response 예시 (`AI_Trend_API`) |
| [ERD](docs/AI_Trend-ERD.png) | PostgreSQL 기준 엔티티 관계(주요 테이블·관계) |

---

## Live Demo

| 항목 | URL |
|------|-----|
| 서비스 | https://aitrend.xn--hu5b25b77nvwc.xn--3e0b707e/ |
| API 명세 (Notion) | https://plum-erigeron-514.notion.site/AI_Trend_API-33b4933e7f1c81198bd5cabc650560e6 |
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
