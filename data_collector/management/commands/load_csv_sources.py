"""
Django management command to load NewsSource from CSV file
"""
from django.core.management.base import BaseCommand
from data_collector.services import NewsSourceCSVService


class Command(BaseCommand):
    help = 'Load NewsSource from NewsSource_RSS.csv file'

    def add_arguments(self, parser):
        parser.add_argument(
            '--csv-file',
            type=str,
            help='CSV 파일 경로 (기본값: NewsSource_RSS.csv)',
        )

    def handle(self, *args, **options):
        csv_service = NewsSourceCSVService()
        csv_file = options.get('csv_file')
        
        # CSV 파일 로드
        results = csv_service.load_sources_from_csv(csv_file)
        
        # 결과 출력
        self.stdout.write("=" * 50)
        self.stdout.write(self.style.SUCCESS("CSV 파일 로드 결과"))
        self.stdout.write("=" * 50)
        self.stdout.write(f"생성: {self.style.SUCCESS(str(results['created']) + '개')}")
        self.stdout.write(f"업데이트: {self.style.WARNING(str(results['updated']) + '개')}")
        self.stdout.write(f"건너뜀: {self.style.WARNING(str(results['skipped']) + '개')}")
        self.stdout.write(f"오류: {self.style.ERROR(str(results['errors']) + '개')}")
        self.stdout.write("=" * 50)
        
        # 오류 상세 정보 출력
        if results.get('error_details') and len(results['error_details']) > 0:
            self.stdout.write("\n" + self.style.ERROR("오류 상세 정보:"))
            self.stdout.write("-" * 50)
            for i, error_detail in enumerate(results['error_details'][:20], 1):  # 최대 20개만 출력
                self.stdout.write(f"\n{i}. Publisher: {error_detail.get('publisher', 'N/A')}")
                self.stdout.write(f"   Title: {error_detail.get('title', 'N/A')}")
                self.stdout.write(f"   URL: {error_detail.get('url', 'N/A')}")
                self.stdout.write(f"   오류: {error_detail.get('error', 'N/A')}")
            if len(results['error_details']) > 20:
                self.stdout.write(f"\n... 외 {len(results['error_details']) - 20}개 오류 더 있음")
            self.stdout.write("-" * 50)
        
        if results['errors'] > 0:
            self.stdout.write(self.style.ERROR("\n일부 오류가 발생했습니다. 위의 오류 상세 정보를 확인하세요."))
        else:
            self.stdout.write(self.style.SUCCESS("\n성공적으로 완료되었습니다!"))

