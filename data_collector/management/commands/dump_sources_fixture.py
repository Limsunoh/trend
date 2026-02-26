"""
로컬 DB에서 NewsSource, SocialMediaSource를 JSON으로 덤프합니다.
DB에 UTF-8이 아닌 문자가 있어도 errors='replace'로 치환해 덤프합니다.
(dumpdata 대신 사용)
"""

import json
from datetime import date, datetime
from pathlib import Path

from django.core.management.base import BaseCommand
from django.db import connection

from data_collector.models import NewsSource, SocialMediaSource


def safe_value(val):
    """JSON으로 쓸 수 있도록, bytes/인코딩 오류를 안전히 변환합니다."""
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


def dump_model_to_fixture_entries(model_class):
    """모델 전체를 raw SQL로 읽어 fixture 항목 리스트로 만듭니다."""
    meta = model_class._meta
    table = meta.db_table
    pk_attr = meta.pk.column
    # 컬럼명 -> 필드명 매핑 (필드명이 fixture에 사용됨)
    col_to_field = {
        f.column: f.name for f in meta.get_fields() if hasattr(f, "column") and f.column
    }

    with connection.cursor() as cursor:
        cursor.execute(f'SELECT * FROM "{table}"')
        columns = [col[0] for col in cursor.description]
        rows = cursor.fetchall()

    entries = []
    for row in rows:
        row_dict = dict(zip(columns, row))
        pk = safe_value(row_dict.get(pk_attr))
        fields = {}
        for col, raw_val in row_dict.items():
            if col == pk_attr:
                continue
            field_name = col_to_field.get(col, col)
            if field_name in ("content_type", "content_type_id"):
                continue
            fields[field_name] = safe_value(raw_val)
        app_label = meta.app_label
        model_name = meta.model_name
        entries.append(
            {
                "model": f"{app_label}.{model_name}",
                "pk": pk,
                "fields": fields,
            }
        )
    return entries


class Command(BaseCommand):
    help = "NewsSource, SocialMediaSource를 JSON fixture로 덤프 (인코딩 오류 자동 치환)"

    def add_arguments(self, parser):
        parser.add_argument(
            "-o",
            "--output",
            type=str,
            default="fixtures/sources_fixture.json",
            help="출력 JSON 파일 경로 (기본: fixtures/sources_fixture.json)",
        )

    def handle(self, *args, **options):
        out_path = Path(options["output"])
        out_path.parent.mkdir(parents=True, exist_ok=True)

        all_entries = []
        for model_class in (NewsSource, SocialMediaSource):
            self.stdout.write(f"{model_class.__name__} 읽는 중...")
            entries = dump_model_to_fixture_entries(model_class)
            all_entries.extend(entries)
            self.stdout.write(f"  → {len(entries)}개")

        with open(out_path, "w", encoding="utf-8") as f:
            json.dump(all_entries, f, ensure_ascii=False, indent=2)

        self.stdout.write(
            self.style.SUCCESS(f"저장: {out_path} ({len(all_entries)}개)")
        )
