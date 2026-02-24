"""
Django management command to clear SocialMediaPost (SNS 게시글) records.
"""

from django.core.management.base import BaseCommand

from data_collector.models import SocialMediaPost


class Command(BaseCommand):
    help = "SNS 게시글(SocialMediaPost) 전부 삭제"

    def add_arguments(self, parser):
        parser.add_argument(
            "--confirm",
            action="store_true",
            help="실제 삭제를 진행하려면 이 플래그를 붙이세요.",
        )

    def handle(self, *args, **options):
        if not options["confirm"]:
            self.stdout.write(
                self.style.WARNING(
                    "⚠️  이 명령어는 모든 SNS 게시글(SocialMediaPost) 데이터를 삭제합니다.\n"
                    "실행하려면 --confirm 플래그를 추가하세요.\n"
                    "예: python manage.py clear_social_posts --confirm"
                )
            )
            return

        count = SocialMediaPost.objects.count()
        self.stdout.write(f"현재 SNS 게시글 수: {count}개")

        if count == 0:
            self.stdout.write(self.style.SUCCESS("삭제할 게시글이 없습니다."))
            return

        deleted_count, _ = SocialMediaPost.objects.all().delete()
        self.stdout.write(
            self.style.SUCCESS(f"✅ 완료: {deleted_count}개 SNS 게시글 삭제됨")
        )
