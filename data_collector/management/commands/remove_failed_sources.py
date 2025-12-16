"""
Django management command to remove NewsSource with failed RSS feeds
"""
from django.core.management.base import BaseCommand
from django.utils import timezone
from datetime import timedelta
from data_collector.models import NewsSource, DataCollectionJob
import feedparser


class Command(BaseCommand):
    help = 'Remove NewsSource with failed RSS feeds'

    def add_arguments(self, parser):
        parser.add_argument(
            '--test',
            action='store_true',
            help='Test RSS feeds without deleting (dry run)',
        )
        parser.add_argument(
            '--confirm',
            action='store_true',
            help='Confirm deletion (required to actually delete)',
        )
        parser.add_argument(
            '--deactivate',
            action='store_true',
            help='Deactivate instead of deleting',
        )
        parser.add_argument(
            '--days',
            type=int,
            default=1,
            help='Check jobs from last N days (default: 1)',
        )

    def handle(self, *args, **options):
        test_mode = options['test']
        confirm = options['confirm']
        deactivate = options['deactivate']
        days = options['days']

        if not test_mode and not confirm:
            self.stdout.write(
                self.style.WARNING(
                    '⚠️  이 명령어는 RSS 피드가 작동하지 않는 NewsSource를 삭제/비활성화합니다.\n'
                    '테스트 모드: python manage.py remove_failed_sources --test\n'
                    '실제 삭제: python manage.py remove_failed_sources --confirm\n'
                    '비활성화: python manage.py remove_failed_sources --confirm --deactivate'
                )
            )
            return

        # 최근 N일간의 수집 작업 확인
        since_date = timezone.now() - timedelta(days=days)
        
        self.stdout.write(f'최근 {days}일간의 수집 작업 분석 중...')
        
        # 활성화된 RSS 소스 조회
        active_sources = NewsSource.objects.filter(
            is_active=True,
            source_type='rss'
        )
        
        failed_sources = []
        
        for source in active_sources:
            # 최근 수집 작업 확인
            recent_jobs = DataCollectionJob.objects.filter(
                source=source,
                started_at__gte=since_date
            ).order_by('-started_at')
            
            if not recent_jobs.exists():
                # 최근 수집 작업이 없으면 RSS 피드 직접 테스트
                self.stdout.write(f'  테스트 중: {str(source)} ({source.url})')
                if not self._test_rss_feed(source.url):
                    failed_sources.append({
                        'source': source,
                        'reason': 'RSS 피드 테스트 실패',
                        'jobs': []
                    })
                continue
            
            # 최근 작업 분석
            latest_job = recent_jobs.first()
            
            # 실패한 작업이 있는지 확인
            failed_jobs = recent_jobs.filter(status='failed')
            zero_article_jobs = recent_jobs.filter(
                status='completed',
                items_collected=0
            )
            
            # 실패한 작업이 있거나, 모든 최근 작업에서 0개 기사만 수집된 경우
            if failed_jobs.exists():
                # 에러 메시지 확인
                error_messages = failed_jobs.values_list('error_message', flat=True)
                error_reasons = [msg for msg in error_messages if msg]
                
                # RSS 피드 자체 문제인지 확인
                is_rss_error = any(
                    'RSS' in msg or '파싱' in msg or 'parse' in msg.lower() or 
                    'urlopen' in msg.lower() or 'getaddrinfo' in msg.lower()
                    for msg in error_reasons
                )
                
                if is_rss_error:
                    # 개수만 필요하므로 count() 사용 (더 효율적)
                    failed_sources.append({
                        'source': source,
                        'reason': f'RSS 피드 오류: {error_reasons[0][:100] if error_reasons else "알 수 없음"}',
                        'jobs_count': failed_jobs.count()  # 전체 실패 작업 개수
                    })
            elif zero_article_jobs.count() >= recent_jobs.count() and recent_jobs.count() >= 2:
                # 최근 작업이 모두 0개 기사이고, 2회 이상 시도한 경우
                # RSS 피드 직접 테스트
                if not self._test_rss_feed(source.url):
                    # 개수만 필요하므로 count() 사용 (더 효율적)
                    failed_sources.append({
                        'source': source,
                        'reason': '최근 수집 작업에서 기사가 0개였고 RSS 피드 테스트 실패',
                        'jobs_count': zero_article_jobs.count()  # 전체 실패 작업 개수
                    })
        
        # 결과 출력
        if not failed_sources:
            self.stdout.write(
                self.style.SUCCESS('✅ 실패한 RSS 피드를 가진 소스가 없습니다.')
            )
            return
        
        self.stdout.write(
            self.style.WARNING(
                f'\n⚠️  실패한 RSS 피드를 가진 소스 {len(failed_sources)}개 발견:\n'
            )
        )
        
        for idx, item in enumerate(failed_sources, 1):
            source = item['source']
            self.stdout.write(
                f'\n{idx}. {str(source)}'
            )
            self.stdout.write(f'   URL: {source.url}')
            self.stdout.write(f'   이유: {item["reason"]}')
            jobs_count = item.get('jobs_count', 0)
            if jobs_count > 0:
                self.stdout.write(f'   최근 실패 작업: {jobs_count}개')
        
        if test_mode:
            self.stdout.write(
                self.style.SUCCESS(
                    f'\n✅ 테스트 모드: {len(failed_sources)}개 소스가 삭제/비활성화 대상입니다.'
                )
            )
            return
        
        # 실제 삭제/비활성화
        if deactivate:
            self.stdout.write('\n비활성화 중...')
            for item in failed_sources:
                source = item['source']
                source.is_active = False
                source.save(update_fields=['is_active'])
                self.stdout.write(
                    self.style.SUCCESS(f'  ✅ 비활성화: {str(source)}')
                )
            self.stdout.write(
                self.style.SUCCESS(
                    f'\n✅ 완료: {len(failed_sources)}개 소스 비활성화됨'
                )
            )
        else:
            self.stdout.write('\n삭제 중...')
            deleted_count = 0
            for item in failed_sources:
                source = item['source']
                source_name = str(source)
                source.delete()
                deleted_count += 1
                self.stdout.write(
                    self.style.SUCCESS(f'  ✅ 삭제: {source_name}')
                )
            self.stdout.write(
                self.style.SUCCESS(
                    f'\n✅ 완료: {deleted_count}개 소스 삭제됨'
                )
            )
    
    def _test_rss_feed(self, rss_url: str) -> bool:
        """
        RSS 피드가 작동하는지 테스트
        
        Returns:
            True: RSS 피드가 정상 작동
            False: RSS 피드가 작동하지 않음
        """
        try:
            feed = feedparser.parse(rss_url)
            
            # 파싱 오류 확인
            if feed.bozo and feed.bozo_exception:
                error_str = str(feed.bozo_exception).lower()
                # 심각한 오류만 실패로 간주
                if 'syntax error' in error_str or 'not well-formed' in error_str:
                    return False
            
            # 기사가 있는지 확인
            if not feed.entries or len(feed.entries) == 0:
                return False
            
            return True
            
        except Exception as e:
            # 네트워크 오류 등
            error_str = str(e).lower()
            if 'urlopen' in error_str or 'getaddrinfo' in error_str or 'timeout' in error_str:
                return False
            # 기타 오류는 일단 True로 처리 (일시적 오류일 수 있음)
            return True

