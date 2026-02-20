# Generated manually - update full_collect_and_analyze schedule from 10min to 1hr

from django.db import migrations


def update_schedule_to_1hour(apps, schema_editor):
    """full_collect_and_analyze 1시간"""
    IntervalSchedule = apps.get_model("django_celery_beat", "IntervalSchedule")
    PeriodicTask = apps.get_model("django_celery_beat", "PeriodicTask")

    # 1시간 간격 스케줄 생성
    schedule, _ = IntervalSchedule.objects.get_or_create(
        every=1,
        period="hours",
    )

    # full_collect_and_analyze 태스크의 interval을 1시간으로 변경
    desc = (
        "전체 수집(뉴스+소셜) 후 전체 분석. 1시간 주기 "
        "(로컬 테스트/서버 6시간은 admin에서 변경)."
    )
    PeriodicTask.objects.filter(name="full_collect_and_analyze").update(
        interval=schedule,
        description=desc,
    )


def revert_to_10min(apps, schema_editor):
    """롤백 시 10분으로 복원"""
    IntervalSchedule = apps.get_model("django_celery_beat", "IntervalSchedule")
    PeriodicTask = apps.get_model("django_celery_beat", "PeriodicTask")

    schedule, _ = IntervalSchedule.objects.get_or_create(
        every=10,
        period="minutes",
    )
    desc = "전체 수집(뉴스+소셜) 후 전체 분석. 로컬 10분/서버 6시간 변경은 admin에서."
    PeriodicTask.objects.filter(name="full_collect_and_analyze").update(
        interval=schedule,
        description=desc,
    )


class Migration(migrations.Migration):

    dependencies = [
        ("analyzer", "0002_add_full_collect_analyze_schedule"),
    ]

    operations = [
        migrations.RunPython(update_schedule_to_1hour, revert_to_10min),
    ]
