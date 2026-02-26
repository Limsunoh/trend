# AGENTS.md

## Cursor Cloud specific instructions

### Project overview
A full-stack real-time trend analysis dashboard (실시간 트렌드 분석 대시보드) that collects Korean news/social media via RSS, performs keyword/trend analysis, and serves results via a React SPA + Django REST API. See `README.md` for details.

### Services

| Service | Command | Port | Notes |
|---------|---------|------|-------|
| PostgreSQL | `sudo service postgresql start` | 5432 | DB: `trend_db`, user: `team_user`, password: `changeme` |
| Redis | `sudo service redis-server start` | 6379 | Required for Django cache and Celery broker |
| Django backend | `python3 manage.py runserver 0.0.0.0:8000` | 8000 | Runs from repo root |
| React frontend | `npm run dev -- --host 0.0.0.0` | 3000 | Runs from `frontend/` dir; proxies `/api` to `:8000` |
| Celery worker | `celery -A trend_analyzer worker -l info -E` | — | Optional for dev unless testing async tasks |

### Important caveats

- **No `python` alias**: This environment uses `python3`, not `python`. All Django management commands must use `python3 manage.py ...`.
- **PATH for pip-installed scripts**: Pip installs scripts to `~/.local/bin`. Ensure `export PATH="$HOME/.local/bin:$PATH"` is in your shell before running `celery`, `black`, `isort`, `flake8`, etc.
- **`python3-dev` required**: The `chroma-hnswlib` package (ChromaDB dependency) needs Python development headers to build. `python3-dev` must be installed before `pip install -r requirements.txt`.
- **`.env` file required**: Django expects a `.env` file in the repo root with at minimum `DB_PASSWORD`, `DB_NAME`, `DB_USER`, `DB_HOST`, `DB_PORT`, `REDIS_HOST`, `REDIS_PORT`. Without it, the app falls back to defaults that expect a local PostgreSQL with no password.
- **Health check shows celery "error"**: The `/api/health/` endpoint reports `celery: error` when no Celery worker is running. This is expected in dev unless you explicitly start a worker.
- **News sources must be loaded**: Run `python3 manage.py load_csv_sources` after migrations to populate the DB with RSS feed sources.
- **Frontend port**: The Vite dev server is configured to run on port **3000** (not 5173), with API proxy to `:8000`.

### Lint / Test / Build

- **Lint**: `black --check .`, `isort --check-only --profile=black .`, `flake8 .` (see `.pre-commit-config.yaml` for exact args)
- **Tests**: `python3 manage.py test analyzer --verbosity=2`
- **Frontend build**: `cd frontend && npm run build`
