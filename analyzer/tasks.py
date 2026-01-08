"""
Celery 작업 모듈

비동기로 키워드 분석 작업을 수행하는 Celery 태스크들을 정의합니다.
"""
import logging
from celery import shared_task
from django.utils import timezone

from analyzer.services import (
    analyze_news_articles,
    analyze_sns_posts,
    compare_platforms
)

logger = logging.getLogger(__name__)


@shared_task(name='analyzer.analyze_keywords_task')
def analyze_keywords_task(days: int = 7, top_n: int = 50):
    """
    뉴스와 SNS 키워드를 분석하는 Celery 작업
    
    이 작업은:
    1. 최근 N일간의 뉴스 기사와 SNS 게시물을 분석합니다
    2. 각 플랫폼별 키워드 빈도를 계산합니다
    3. 정규화된 빈도로 변환합니다
    4. 상위 N개 키워드를 반환합니다
    
    Args:
        days: 최근 며칠간의 데이터를 분석할지 (기본값: 7)
        top_n: 상위 N개 키워드만 반환 (기본값: 50)
        
    Returns:
        분석 결과 딕셔너리
        
    사용 예시:
        # Celery로 비동기 실행
        result = analyze_keywords_task.delay(days=7, top_n=50)
        
        # 동기 실행 (테스트용)
        result = analyze_keywords_task(days=7, top_n=50)
    """
    try:
        logger.info(f"키워드 분석 작업 시작: 최근 {days}일간, 상위 {top_n}개")
        
        # 뉴스 분석
        news_result = analyze_news_articles(days=days, top_n=top_n)
        
        # SNS 분석
        sns_result = analyze_sns_posts(days=days, top_n=top_n)
        
        logger.info(
            f"키워드 분석 완료: "
            f"뉴스 {news_result['total_articles']}개, "
            f"SNS {sns_result['total_posts']}개"
        )
        
        return {
            'status': 'success',
            'news': news_result,
            'sns': sns_result,
            'analyzed_at': timezone.now().isoformat()
        }
        
    except Exception as e:
        logger.error(f"키워드 분석 작업 실패: {str(e)}", exc_info=True)
        return {
            'status': 'error',
            'error': str(e),
            'analyzed_at': timezone.now().isoformat()
        }


@shared_task(name='analyzer.compare_platforms_task')
def compare_platforms_task(days: int = 7, top_n: int = 30, min_frequency: float = 0.001):
    """
    뉴스와 SNS 플랫폼을 비교 분석하는 Celery 작업
    
    이 작업은:
    1. 최근 N일간의 뉴스와 SNS 데이터를 분석합니다
    2. 공통 키워드를 찾아 비교합니다
    3. 플랫폼별 차이를 분석합니다
    
    Args:
        days: 최근 며칠간의 데이터를 분석할지 (기본값: 7)
        top_n: 상위 N개 공통 키워드만 반환 (기본값: 30)
        min_frequency: 최소 상대 빈도 (기본값: 0.001 = 0.1%)
        
    Returns:
        비교 분석 결과 딕셔너리
        
    사용 예시:
        # Celery로 비동기 실행
        result = compare_platforms_task.delay(days=7, top_n=30)
    """
    try:
        logger.info(
            f"플랫폼 비교 분석 작업 시작: "
            f"최근 {days}일간, 상위 {top_n}개, 최소 빈도 {min_frequency}"
        )
        
        # 플랫폼 비교 분석
        result = compare_platforms(
            days=days,
            top_n=top_n,
            min_frequency=min_frequency
        )
        
        logger.info(
            f"플랫폼 비교 분석 완료: "
            f"공통 키워드 {result['summary']['common_keywords_count']}개"
        )
        
        return {
            'status': 'success',
            'result': result,
            'analyzed_at': timezone.now().isoformat()
        }
        
    except Exception as e:
        logger.error(f"플랫폼 비교 분석 작업 실패: {str(e)}", exc_info=True)
        return {
            'status': 'error',
            'error': str(e),
            'analyzed_at': timezone.now().isoformat()
        }


@shared_task(name='analyzer.update_hot_keywords')
def update_hot_keywords(days: int = 1, top_n: int = 20):
    """
    실시간 인기 키워드를 업데이트하는 Celery 작업
    
    이 작업은:
    1. 최근 1일간의 데이터를 분석합니다 (기본값)
    2. 뉴스와 SNS 각각의 상위 키워드를 추출합니다
    3. 급상승 키워드를 식별합니다
    
    주기적으로 실행하여 실시간 트렌드를 파악하는 용도입니다.
    
    Args:
        days: 최근 며칠간의 데이터를 분석할지 (기본값: 1)
        top_n: 상위 N개 키워드만 반환 (기본값: 20)
        
    Returns:
        인기 키워드 딕셔너리
        
    사용 예시:
        # Celery로 주기적 실행 (celery beat 설정 필요)
        # settings.py의 CELERY_BEAT_SCHEDULE에 추가:
        # 'update-hot-keywords': {
        #     'task': 'analyzer.update_hot_keywords',
        #     'schedule': crontab(minute='*/30'),  # 30분마다
        # },
    """
    try:
        logger.info(f"인기 키워드 업데이트 시작: 최근 {days}일간, 상위 {top_n}개")
        
        # 뉴스 인기 키워드
        news_result = analyze_news_articles(days=days, top_n=top_n)
        
        # SNS 인기 키워드
        sns_result = analyze_sns_posts(days=days, top_n=top_n)
        
        # 공통 키워드 찾기
        common_keywords = []
        news_top = {item['keyword']: item['frequency'] 
                   for item in news_result['top_keywords']}
        sns_top = {item['keyword']: item['frequency'] 
                   for item in sns_result['top_keywords']}
        
        for keyword in set(news_top.keys()) & set(sns_top.keys()):
            common_keywords.append({
                'keyword': keyword,
                'news_frequency': news_top[keyword],
                'sns_frequency': sns_top[keyword]
            })
        
        logger.info(f"인기 키워드 업데이트 완료: 공통 키워드 {len(common_keywords)}개")
        
        return {
            'status': 'success',
            'news_hot_keywords': news_result['top_keywords'],
            'sns_hot_keywords': sns_result['top_keywords'],
            'common_keywords': common_keywords,
            'updated_at': timezone.now().isoformat()
        }
        
    except Exception as e:
        logger.error(f"인기 키워드 업데이트 실패: {str(e)}", exc_info=True)
        return {
            'status': 'error',
            'error': str(e),
            'updated_at': timezone.now().isoformat()
        }
