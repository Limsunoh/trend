"""
시간차 분석 관리 명령어

사용법:
    # 최근 7일간 시간차 분석
    python manage.py analyze_time_lag
    
    # 최근 30일간 분석
    python manage.py analyze_time_lag --days 30
    
    # 상위 20개 키워드만 분석
    python manage.py analyze_time_lag --top-n 20
    
    # 특정 키워드의 타임라인 분석
    python manage.py analyze_time_lag --keyword "달러" --timeline
"""
from django.core.management.base import BaseCommand
from analyzer.services import (
    analyze_time_lag,
    get_keyword_timeline,
    get_multiple_keywords_timeline
)
from datetime import timedelta


class Command(BaseCommand):
    help = '뉴스와 SNS 간의 키워드 전파 패턴(시간차)을 분석합니다.'

    def add_arguments(self, parser):
        """명령어 인자 추가"""
        parser.add_argument(
            '--days',
            type=int,
            default=7,
            help='최근 며칠간의 데이터를 분석할지 (기본값: 7)'
        )
        
        parser.add_argument(
            '--top-n',
            type=int,
            default=50,
            help='상위 N개 키워드만 분석 (기본값: 50)'
        )
        
        parser.add_argument(
            '--min-frequency',
            type=float,
            default=0.001,
            help='최소 상대 빈도 (기본값: 0.001 = 0.1%%)'
        )
        
        parser.add_argument(
            '--keyword',
            type=str,
            help='특정 키워드의 타임라인만 분석 (타임라인 모드)'
        )
        
        parser.add_argument(
            '--timeline',
            action='store_true',
            help='타임라인 데이터 생성 (시각화용)'
        )
        
        parser.add_argument(
            '--interval-hours',
            type=int,
            default=6,
            help='타임라인 시간대별 집계 간격 (시간 단위, 기본값: 6)'
        )

    def handle(self, *args, **options):
        """명령어 실행"""
        days = options['days']
        top_n = options['top_n']
        min_frequency = options['min_frequency']
        keyword = options.get('keyword')
        timeline = options.get('timeline', False)
        interval_hours = options['interval_hours']
        
        self.stdout.write("=" * 80)
        self.stdout.write(self.style.SUCCESS("시간차 분석 시작"))
        self.stdout.write("=" * 80)
        self.stdout.write(f"분석 기간: 최근 {days}일")
        
        # 특정 키워드 타임라인 분석
        if keyword:
            self._analyze_keyword_timeline(keyword, days, interval_hours)
            return
        
        # 시간차 분석 실행
        try:
            result = analyze_time_lag(
                keywords=None,  # 공통 키워드 자동 추출
                days=days,
                min_frequency=min_frequency,
                top_n=top_n
            )
            
            keywords = result['keywords']
            statistics = result['statistics']
            
            # 통계 출력
            self.stdout.write("\n[시간차 분석 통계]")
            self.stdout.write("-" * 80)
            self.stdout.write(
                self.style.SUCCESS(
                    f"✅ 분석 완료: {statistics['total_keywords']}개 키워드\n"
                    f"  - 뉴스 → SNS: {statistics['news_to_sns']}개 "
                    f"({statistics['news_to_sns_percentage']:.1f}%)\n"
                    f"  - SNS → 뉴스: {statistics['sns_to_news']}개 "
                    f"({statistics['sns_to_news_percentage']:.1f}%)\n"
                    f"  - 동시 등장: {statistics['simultaneous']}개\n"
                    f"  - 뉴스 전용: {statistics['news_only']}개\n"
                    f"  - SNS 전용: {statistics['sns_only']}개"
                )
            )
            
            if statistics['avg_time_lag_news_to_sns_hours']:
                self.stdout.write(
                    f"\n  - 뉴스 → SNS 평균 시간차: "
                    f"{statistics['avg_time_lag_news_to_sns_hours']:.2f}시간"
                )
            
            if statistics['avg_time_lag_sns_to_news_hours']:
                self.stdout.write(
                    f"  - SNS → 뉴스 평균 시간차: "
                    f"{statistics['avg_time_lag_sns_to_news_hours']:.2f}시간"
                )
            
            # 키워드별 상세 결과 출력
            if keywords:
                self.stdout.write("\n[키워드별 분석 결과]")
                self.stdout.write("-" * 80)
                
                # 방향별로 그룹화
                news_to_sns = [
                    k for k in keywords 
                    if k['direction'] == 'news_to_sns'
                ]
                sns_to_news = [
                    k for k in keywords 
                    if k['direction'] == 'sns_to_news'
                ]
                
                # 뉴스 → SNS
                if news_to_sns:
                    self.stdout.write("\n📰 → 📱 뉴스 → SNS 전파:")
                    # 시간차 순으로 정렬 (빠른 순)
                    news_to_sns.sort(key=lambda x: x['time_lag_hours'] or 9999)
                    for i, item in enumerate(news_to_sns[:10], 1):
                        hours = item['time_lag_hours']
                        if hours:
                            self.stdout.write(
                                f"  {i:2d}. {item['keyword']:20s} "
                                f"시간차: {hours:.2f}시간 "
                                f"(뉴스: {item['news_first_occurrence'].strftime('%Y-%m-%d %H:%M')}, "
                                f"SNS: {item['sns_first_occurrence'].strftime('%Y-%m-%d %H:%M')})"
                            )
                
                # SNS → 뉴스
                if sns_to_news:
                    self.stdout.write("\n📱 → 📰 SNS → 뉴스 전파:")
                    sns_to_news.sort(key=lambda x: x['time_lag_hours'] or 9999)
                    for i, item in enumerate(sns_to_news[:10], 1):
                        hours = item['time_lag_hours']
                        if hours:
                            self.stdout.write(
                                f"  {i:2d}. {item['keyword']:20s} "
                                f"시간차: {hours:.2f}시간 "
                                f"(SNS: {item['sns_first_occurrence'].strftime('%Y-%m-%d %H:%M')}, "
                                f"뉴스: {item['news_first_occurrence'].strftime('%Y-%m-%d %H:%M')})"
                            )
            
            # 타임라인 데이터 생성 (선택적)
            if timeline and keywords:
                self.stdout.write("\n[타임라인 데이터 생성]")
                self.stdout.write("-" * 80)
                
                # 상위 키워드들의 타임라인 생성
                top_keywords = [
                    k['keyword'] for k in keywords[:10]
                    if k['direction'] in ['news_to_sns', 'sns_to_news']
                ]
                
                if top_keywords:
                    timeline_data = get_multiple_keywords_timeline(
                        top_keywords, days, interval_hours
                    )
                    self.stdout.write(
                        self.style.SUCCESS(
                            f"✅ {len(top_keywords)}개 키워드의 타임라인 데이터 생성 완료"
                        )
                    )
                    self.stdout.write(
                        f"   (시각화에 사용 가능: timeline_data['timelines'])"
                    )
                
        except Exception as e:
            self.stdout.write(
                self.style.ERROR(f"❌ 시간차 분석 실패: {str(e)}")
            )
            import traceback
            self.stdout.write(traceback.format_exc())
        
        self.stdout.write("")
        self.stdout.write("=" * 80)
        self.stdout.write(self.style.SUCCESS("분석 완료"))
        self.stdout.write("=" * 80)
    
    def _analyze_keyword_timeline(self, keyword: str, days: int, interval_hours: int):
        """특정 키워드의 타임라인 분석"""
        self.stdout.write(f"키워드: {keyword}")
        self.stdout.write("-" * 80)
        
        try:
            timeline_data = get_keyword_timeline(
                keyword, days, interval_hours
            )
            
            self.stdout.write(
                self.style.SUCCESS(f"✅ 타임라인 데이터 생성 완료")
            )
            
            if timeline_data['news_first_occurrence']:
                self.stdout.write(
                    f"\n뉴스 최초 등장: {timeline_data['news_first_occurrence']}"
                )
            if timeline_data['sns_first_occurrence']:
                self.stdout.write(
                    f"SNS 최초 등장: {timeline_data['sns_first_occurrence']}"
                )
            
            self.stdout.write(
                f"\n시간대별 집계 간격: {interval_hours}시간"
            )
            self.stdout.write(f"시간 구간 수: {len(timeline_data['time_labels'])}개")
            
            # 타임라인 데이터 요약
            if timeline_data['time_labels']:
                self.stdout.write("\n[타임라인 요약]")
                self.stdout.write("시간대 | 뉴스 | SNS")
                self.stdout.write("-" * 40)
                for i, (label, news_count, sns_count) in enumerate(zip(
                    timeline_data['time_labels'],
                    timeline_data['news_timeline'],
                    timeline_data['sns_timeline']
                )):
                    if news_count > 0 or sns_count > 0:
                        self.stdout.write(
                            f"{label} | {news_count:5d} | {sns_count:5d}"
                        )
                        if i >= 20:  # 최대 20개만 표시
                            self.stdout.write("... (더 많은 데이터 있음)")
                            break
            
        except Exception as e:
            self.stdout.write(
                self.style.ERROR(f"❌ 타임라인 분석 실패: {str(e)}")
            )
            import traceback
            self.stdout.write(traceback.format_exc())

