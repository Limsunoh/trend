# Docker 실행 가이드

## 사전 준비

1. `.env` 파일 생성 (프로젝트 루트)
   ```bash
   cp .env.docker.example .env
   # .env 에 SECRET_KEY, DB_PASSWORD 등 수정
   ```

2. Docker, Docker Compose 설치

## 실행

```bash
# 이미지 빌드 + 전체 스택 기동
docker compose up -d --build

# 로그 확인
docker compose logs -f

# 중지
docker compose down
```

## 서비스

| 서비스        | 포트  | 설명              |
|---------------|-------|-------------------|
| web           | 8000  | Django API        |
| db            | 5432  | PostgreSQL        |
| redis         | 6379  | Redis             |
| celery_worker | -     | Celery Worker     |
| celery_beat   | -     | Celery Beat 스케줄러 |

## 접속

- API: http://localhost:8000
- Swagger: http://localhost:8000/api/schema/swagger-ui/

## 볼륨

- `postgres_data`: PostgreSQL 데이터 영구 보관
- `docker compose down -v` 시 볼륨 삭제됨 (데이터 소실 주의)
