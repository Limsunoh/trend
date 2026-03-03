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

## Django superuser 만들기

Docker Compose로 띄운 DB를 쓰는 웹 컨테이너에서 Django 관리자(superuser) 계정을 만듭니다. 실행 후 터미널에서 username, email, password를 입력하라는 프롬프트가 나옵니다.

```bash
docker compose exec web python manage.py createsuperuser
```

## 볼륨

- `postgres_data`: PostgreSQL 데이터 영구 보관
- `docker compose down -v` 시 볼륨 삭제됨 (데이터 소실 주의)
- `./fixtures` → web 컨테이너 `/app/fixtures` (시드/백업 JSON 넣을 곳)

## DB 초기화 후 NewsSource / SocialMediaSource 복원

`docker compose down -v` 후 DB가 비었을 때, 로컬 DB에 있던 소스 데이터만 다시 넣는 방법입니다.

### 1단계: 로컬 DB에서 덤프 (로컬에서 로컬 DB 사용 중일 때)

프로젝트 루트에서 **로컬 DB를 쓰는 설정**으로 실행합니다.

**방법 A – 연결 시 인코딩 오류(0xbe 등) 나면 이걸 사용 (권장):**

로컬 DB는 **5432**, Docker DB는 **5433**입니다. 소스는 **로컬(5432)**에서 덤프해 **Docker(5433)**에 loaddata로 넣습니다.

```bash
# Django 없이 .env를 UTF-8로 읽어 로컬(5432)에 접속해 덤프 → 인코딩 오류 회피
python scripts/dump_sources_from_local_db.py -o fixtures/sources_fixture.json
```

**방법 B – Django management command (연결은 정상일 때):**

```bash
python manage.py dump_sources_fixture -o fixtures/sources_fixture.json
```

- **연결 시** `UnicodeDecodeError: 'utf-8' codec can't decode byte 0xbe...` 가 나오면: 방법 A 스크립트를 쓰거나, `.env`를 **UTF-8**로 저장하고 `DB_PASSWORD`를 영문/숫자만 쓰세요.

**방법 B – 일반 덤프:**

```bash
python manage.py dumpdata data_collector.NewsSource data_collector.SocialMediaSource --indent 2 -o fixtures/sources_fixture.json
```

`fixtures/sources_fixture.json` 파일이 생성됩니다. (폴더 없으면 `mkdir fixtures` 후 실행)

### 2단계: Docker DB에 로드

1. **settings.py 수정 후에는 이미지를 다시 빌드해야 합니다.** (FIXTURE_DIRS 반영)

   ```bash
   docker compose up -d --build
   ```

2. 프로젝트 루트에 `fixtures/sources_fixture.json`이 있는지 확인한 뒤:

   ```bash
   docker compose exec web python manage.py loaddata sources_fixture
   ```

- `./fixtures`가 컨테이너 `/app/fixtures`에 마운트되고, `FIXTURE_DIRS`가 이 경로를 포함하므로 `loaddata sources_fixture`로 로드됩니다.
- **"The \"ryj\" variable is not set"** 경고: `.env` 값에 `$`가 있으면 Docker가 변수로 해석합니다. 해당 값에서 `$`를 `$$`로 바꾸면 됩니다.

- 이미 Docker를 다시 띄우기 전이라면: 1단계로 JSON 생성 → `docker compose up -d` 후 2단계 실행하면 됩니다.

### loaddata 시 UTF-8 / UnicodeDecodeError

덤프된 `sources_fixture.json`을 Docker DB(5433)에 넣을 때 `UnicodeDecodeError` 또는 UTF-8 관련 에러가 나면, **덤프 파일을 인코딩 안전 스크립트로 다시 만든 뒤** 같은 loaddata를 다시 실행하면 됩니다.

1. **덤프를 인코딩 안전 스크립트로 다시 생성** (로컬 DB 5432에서, 깨진 문자는 자동 치환됨):

   ```bash
   python scripts/dump_sources_from_local_db.py -o fixtures/sources_fixture.json
   ```

2. **Docker DB에 로드** (필요 시 UTF-8 강제):

   ```bash
   docker compose exec -e PYTHONUTF8=1 web python manage.py loaddata sources_fixture
   ```

- `manage.py dump_sources_fixture`나 `dumpdata`로 만든 JSON은 로컬 DB에 깨진 문자가 있으면 그대로 들어가서, loaddata 시 에러가 날 수 있습니다. 이 경우 위 1번 스크립트로 덤프를 다시 만들면 됩니다.

## 문제 해결

### "password authentication failed for user team_user"

DB 사용자 비밀번호는 **최초 볼륨 생성 시점**에만 적용됩니다. 나중에 `.env`의 `DB_PASSWORD`를 바꿔도 이미 만들어진 DB에는 반영되지 않습니다.

**해결:** 반드시 **프로젝트 루트**(docker-compose.yml과 .env가 있는 폴더)에서 실행하세요. 데이터를 지워도 되면 볼륨을 삭제한 뒤 다시 올리세요.

```bash
# 프로젝트 루트에서 실행 (예: c:\...\trend)
docker compose down -v
docker compose up -d --build
```

이후 DB는 **현재 디렉터리의 .env**에 있는 `DB_PASSWORD`로 초기화됩니다. (기존 DB 데이터는 모두 삭제됩니다.) 다른 폴더에서 `docker compose`를 실행하면 .env를 못 찾아 비밀번호가 기본값(`changeme`)으로 들어갈 수 있습니다.

### "relation django_celery_beat_periodictask does not exist"

Celery beat가 web의 migrate가 끝나기 전에 DB를 조회해서 발생합니다. `docker-compose.yml`에서 beat/worker는 web이 **healthy**(헬스체크 통과)된 뒤에만 시작하도록 되어 있습니다. 위처럼 `down -v` 후 `up -d --build`로 다시 올리면 해결됩니다.
