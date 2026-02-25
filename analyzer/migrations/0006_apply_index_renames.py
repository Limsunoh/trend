# Merge 이후 DB에만 인덱스 이름 변경 적용 (0002/0004는 state만 반영)

from django.db import migrations


def rename_indexes(apps, schema_editor):
    op = schema_editor.connection.ops
    with schema_editor.connection.cursor() as cursor:
        for old_name, new_name in [
            ("analyzer_tr_analysis_6e76f2_idx", "analyzer_tr_analysi_60a193_idx"),
            ("analyzer_tr_analysis_7c4a44_idx", "analyzer_tr_analysi_1d0216_idx"),
        ]:
            q_old, q_new = op.quote_name(old_name), op.quote_name(new_name)
            cursor.execute(
                "ALTER INDEX IF EXISTS %s RENAME TO %s" % (q_old, q_new)
            )


class Migration(migrations.Migration):

    dependencies = [
        ("analyzer", "0005_merge_20260225_0000"),
    ]

    operations = [
        migrations.RunPython(rename_indexes, migrations.RunPython.noop),
    ]
