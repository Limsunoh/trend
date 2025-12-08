"""
Django management command to clear all NewsArticle records
"""
from django.core.management.base import BaseCommand
from data_collector.models import NewsArticle
from common.redis_services import DuplicatePreventionService


class Command(BaseCommand):
    help = 'Clear all NewsArticle records and Redis duplicate cache'

    def add_arguments(self, parser):
        parser.add_argument(
            '--confirm',
            action='store_true',
            help='Confirm deletion (required to actually delete)',
        )

    def handle(self, *args, **options):
        if not options['confirm']:
            self.stdout.write(
                self.style.WARNING(
                    '⚠️  이 명령어는 모든 NewsArticle 데이터를 삭제합니다.\n'
                    '실행하려면 --confirm 플래그를 추가하세요.\n'
                    '예: python manage.py clear_articles --confirm'
                )
            )
            return

        # 기사 개수 확인
        article_count = NewsArticle.objects.count()
        self.stdout.write(f'현재 기사 수: {article_count}개')

        if article_count == 0:
            self.stdout.write(self.style.SUCCESS('삭제할 기사가 없습니다.'))
            return

        # Redis 중복 체크 캐시 삭제
        self.stdout.write('Redis 중복 체크 캐시 삭제 중...')
        duplicate_service = DuplicatePreventionService()
        try:
            # collected:news:* 패턴의 모든 키 삭제
            pattern = f"{duplicate_service.DUPLICATE_PREFIX}news:*"
            keys = duplicate_service.client.keys(pattern)
            if keys:
                duplicate_service.client.delete(*keys)
                self.stdout.write(
                    self.style.SUCCESS(f'Redis 캐시 {len(keys)}개 삭제 완료')
                )
            else:
                self.stdout.write('Redis 캐시가 비어있습니다.')
        except Exception as e:
            self.stdout.write(
                self.style.WARNING(f'Redis 캐시 삭제 오류: {str(e)}')
            )

        # DB 기사 삭제
        self.stdout.write('데이터베이스 기사 삭제 중...')
        deleted_count, _ = NewsArticle.objects.all().delete()
        
        self.stdout.write(
            self.style.SUCCESS(
                f'✅ 완료: {deleted_count}개 기사 삭제됨'
            )
        )

