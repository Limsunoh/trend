"""
트렌드 동기화 분석 관리 명령어

사용법:
    # 최근 7일간 트렌드 동기화 분석
    python manage.py analyze_trend_synchronization
    
    # 최근 30일간 분석
    python manage.py analyze_trend_synchronization --days 30
    
    # 상위 20개 동기화/비동기화 키워드만 출력
    python manage.py analyze_trend_synchronization --top-n 20
    
    # 3시간 단위로 집계
    python manage.py analyze_trend_synchronization --interval-hours 3
"""
from django.core.management.base import BaseCommand
from analyzer.services import analyze_trend_synchronization


class Command(BaseCommand):
    help = '뉴스와 SNS의 트렌드 동기화 정도를 분석합니다.'

    def add_arguments(self, parser):
        """명령어 인자 추가"""
        parser.add_argument(
            '--days',
            type=int,
            default=7,
            help='최근 며칠간의 데이터를 분석할지 (기본값: 7)'
        )
        
        parser.add_argument(
            '--interval-hours',
            type=int,
            default=6,
            help='시간대별 집계 간격 (시간 단위, 기본값: 6)'
        )
        
        parser.add_argument(
            '--min-frequency',
            type=float,
            default=0.001,
            help='최소 상대 빈도 (기본값: 0.001 = 0.1%%)'
        )
        
        parser.add_argument(
            '--top-n',
            type=int,
            help='상위 N개 키워드만 출력 (None이면 전체)'
        )

    def handle(self, *args, **options):
        """명령어 실행"""
        days = options['days']
        interval_hours = options['interval_hours']
        min_frequency = options['min_frequency']
        top_n = options.get('top_n')
        
        self.stdout.write("=" * 80)
        self.stdout.write(self.style.SUCCESS("트렌드 동기화 분석 시작"))
        self.stdout.write("=" * 80)
        self.stdout.write(f"분석 기간: 최근 {days}일")
        self.stdout.write(f"시간대 간격: {interval_hours}시간")
        self.stdout.write("")
        
        try:
            result = analyze_trend_synchronization(
                days=days,
                interval_hours=interval_hours,
                min_frequency=min_frequency,
                top_n=top_n
            )
            
            # 동기화된 키워드 출력
            if result['synchronized_keywords']:
                self.stdout.write(self.style.SUCCESS("\n[동기화된 키워드] (상관관계 ≥ 0.7)"))
                self.stdout.write("-" * 80)
                for i, item in enumerate(result['synchronized_keywords'], 1):
                    self.stdout.write(
                        f"{i}. {item['keyword']} "
                        f"(상관관계: {item['correlation']:.3f}, "
                        f"뉴스 평균: {item['avg_news_frequency']:.4f}, "
                        f"SNS 평균: {item['avg_sns_frequency']:.4f})"
                    )
            else:
                self.stdout.write(self.style.WARNING("\n동기화된 키워드 없음"))
            
            # 비동기화된 키워드 출력
            if result['desynchronized_keywords']:
                self.stdout.write(self.style.WARNING("\n[비동기화된 키워드] (상관관계 < 0.3)"))
                self.stdout.write("-" * 80)
                for i, item in enumerate(result['desynchronized_keywords'], 1):
                    self.stdout.write(
                        f"{i}. {item['keyword']} "
                        f"(상관관계: {item['correlation']:.3f}, "
                        f"뉴스 평균: {item['avg_news_frequency']:.4f}, "
                        f"SNS 평균: {item['avg_sns_frequency']:.4f})"
                    )
            else:
                self.stdout.write(self.style.SUCCESS("\n비동기화된 키워드 없음"))
            
            # 요약 통계
            summary = result['summary']
            self.stdout.write(self.style.SUCCESS("\n[요약 통계]"))
            self.stdout.write("-" * 80)
            self.stdout.write(f"전체 공통 키워드: {summary['total_common_keywords']}개")
            self.stdout.write(f"분석된 키워드: {summary['analyzed_keywords']}개")
            self.stdout.write(f"동기화된 키워드: {summary['synchronized_count']}개")
            self.stdout.write(f"비동기화된 키워드: {summary['desynchronized_count']}개")
            self.stdout.write(f"평균 상관관계: {summary['avg_correlation']:.3f}")
            self.stdout.write(f"시간대 버킷 수: {summary['time_buckets_count']}개")
            
            # 상관관계 해석
            avg_corr = summary['avg_correlation']
            if avg_corr >= 0.7:
                self.stdout.write(
                    self.style.SUCCESS(
                        f"\n✅ 뉴스와 SNS의 트렌드가 높은 동기화를 보입니다."
                    )
                )
            elif avg_corr >= 0.3:
                self.stdout.write(
                    self.style.WARNING(
                        f"\n⚠️  뉴스와 SNS의 트렌드가 중간 수준의 동기화를 보입니다."
                    )
                )
            else:
                self.stdout.write(
                    self.style.WARNING(
                        f"\n⚠️  뉴스와 SNS의 트렌드가 낮은 동기화를 보입니다."
                    )
                )
            
        except Exception as e:
            self.stdout.write(
                self.style.ERROR(f"트렌드 동기화 분석 실패: {str(e)}")
            )
            raise


