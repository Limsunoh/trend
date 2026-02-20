# Generated manually for full_collect_and_analyze periodic task

from django.db import migrations


def create_full_collect_analyze_schedule(apps, schema_editor):
    """10분마다 전체 수집+분석 태스크를 실행하는 스케줄 생성 (로컬 테스트용)"""
    IntervalSchedule = apps.get_model("django_celery_beat", "IntervalSchedule")
    PeriodicTask = apps.get_model("django_celery_beat", "PeriodicTask")

    # 10분 간격 스케줄 (period: 'seconds','minutes','hours','days')
    schedule, _ = IntervalSchedule.objects.get_or_create(
        every=10,
        period="minutes",
    )

    # 이미 존재하면 스킵 (migrate --run-syncdb 시 중복 방지)
    if PeriodicTask.objects.filter(name="full_collect_and_analyze").exists():
        return

    PeriodicTask.objects.create(
        name="full_collect_and_analyze",
        task="analyzer.full_collect_and_analyze_task",
        interval=schedule,
        enabled=True,
        description="전체 수집(뉴스+소셜) 후 전체 분석. 로컬 10분/서버 6시간 변경은 admin에서.",
    )


def remove_full_collect_analyze_schedule(apps, schema_editor):
    """롤백 시 스케줄 제거"""
    PeriodicTask = apps.get_model("django_celery_beat", "PeriodicTask")
    PeriodicTask.objects.filter(name="full_collect_and_analyze").delete()


class Migration(migrations.Migration):

    dependencies = [
        ("analyzer", "0001_trend_analysis_result"),
        ("django_celery_beat", "0001_initial"),
    ]

    operations = [
        migrations.RunPython(create_full_collect_analyze_schedule, remove_full_collect_analyze_schedule),
    ]
