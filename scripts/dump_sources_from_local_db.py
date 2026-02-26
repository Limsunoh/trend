#!/usr/bin/env python3
"""
Django 없이 로컬 PostgreSQL(5432)에서 NewsSource, SocialMediaSource만 덤프합니다.
.env를 UTF-8(에러 시 치환)로 읽어 연결 인코딩 오류를 피합니다.
사용: 로컬 DB 5432 → fixtures/sources_fixture.json → Docker에서 loaddata로 5433에 로드

  python scripts/dump_sources_from_local_db.py
  python scripts/dump_sources_from_local_db.py -o fixtures/sources_fixture.json
"""

import json
import os
import sys
from datetime import date, datetime
from pathlib import Path

# 프로젝트 루트를 path에 넣기 (Django 부트스트랩 없이 psycopg2만 사용)
PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

# .env를 UTF-8(에러 시 치환)로 읽어서 os.environ에 넣기 → 이후 psycopg2가 사용
_env_path = PROJECT_ROOT / ".env"
if _env_path.exists():
    with open(_env_path, "r", encoding="utf-8", errors="replace") as f:
        for line in f:
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, _, v = line.partition("=")
                k, v = k.strip(), v.strip().strip('"').strip("'")
                os.environ.setdefault(k, v)

import psycopg2  # noqa: E402

# 로컬 DB = 5432 (Docker DB = 5433)
DB_CONFIG = {
    "host": os.environ.get("DB_HOST", "localhost"),
    "port": os.environ.get("DB_PORT", "5432"),
    "dbname": os.environ.get("DB_NAME", "trend_db"),
    "user": os.environ.get("DB_USER", "team_user"),
    "password": os.environ.get("DB_PASSWORD", ""),
}


def safe_value(val):
    if val is None:
        return None
    if isinstance(val, bytes):
        return val.decode("utf-8", errors="replace")
    if isinstance(val, str):
        return val.encode("utf-8", errors="replace").decode("utf-8")
    if isinstance(val, (datetime, date)):
        return val.isoformat()
    if isinstance(val, (dict, list)):
        return val
    return val


# 테이블별 (테이블명, pk컬럼, fixture용 model 이름, 제외 컬럼)
TABLES = [
    ("data_collector_newssource", "id", "data_collector.newssource", set()),
    (
        "data_collector_socialmediasource",
        "id",
        "data_collector.socialmediasource",
        set(),
    ),
]


def main():
    out_path = PROJECT_ROOT / "fixtures" / "sources_fixture.json"
    if "-o" in sys.argv:
        i = sys.argv.index("-o")
        if i + 1 < len(sys.argv):
            out_path = Path(sys.argv[i + 1])
    out_path.parent.mkdir(parents=True, exist_ok=True)

    # 연결 시 전달되는 값이 UTF-8로 안전하도록 정규화
    def safe_conn(s):
        return (s or "").encode("utf-8", errors="replace").decode("utf-8")

    conn_params = {k: safe_conn(v) for k, v in DB_CONFIG.items()}

    all_entries = []
    with psycopg2.connect(**conn_params) as conn:
        with conn.cursor() as cur:
            for table, pk_col, model_label, skip_cols in TABLES:
                cur.execute(f'SELECT * FROM "{table}"')
                cols = [d[0] for d in cur.description]
                rows = cur.fetchall()
                for row in rows:
                    row_dict = dict(zip(cols, row))
                    pk = safe_value(row_dict.get(pk_col))
                    fields = {}
                    for col, val in row_dict.items():
                        if col == pk_col or col in skip_cols:
                            continue
                        fields[col] = safe_value(val)
                    all_entries.append(
                        {
                            "model": model_label,
                            "pk": pk,
                            "fields": fields,
                        }
                    )
                print(f"  {table}: {len(rows)}개")

    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(all_entries, f, ensure_ascii=False, indent=2)
    print(f"저장: {out_path} ({len(all_entries)}개)")


if __name__ == "__main__":
    main()
