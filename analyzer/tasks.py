"""
Celery 작업 모듈

비동기로 키워드 분석 작업을 수행하는 Celery 태스크들을 정의합니다.
"""
import logging
from typing import Optional, List, Dict
from celery import shared_task
from django.utils import timezone

from analyzer.services import (
    analyze_news_articles,
    analyze_sns_posts,
    compare_platforms,
    analyze_time_lag,
    detect_surge_keywords,
    analyze_trend_synchronization,
    analyze_hourly_trends,
    get_keyword_occurrence_times,
    get_multiple_keywords_timeline,
    get_keyword_timeline,
    analyze_engagement_keywords
)
from analyzer.result_storage import (
    store_analysis_result,
    cache_latest_analysis
)

logger = logging.getLogger(__name__)


def _store_and_cache_result(
    analysis_type: str,
    result_payload: Dict,
    parameters: Optional[Dict] = None,
    platform: Optional[str] = None,
    days: Optional[int] = None,
    summary: Optional[Dict] = None
):
    try:
        # DB에 이력 저장
        store_analysis_result(
            analysis_type=analysis_type,
            result=result_payload,
            parameters=parameters,
            platform=platform,
            days=days,
            summary=summary
        )
        # Redis에는 최신 결과만 캐시
        cache_latest_analysis(
            analysis_type=analysis_type,
            result=result_payload,
            parameters=parameters,
            platform=platform,
            days=days
        )
    except Exception as e:
        # 저장 실패는 태스크 실패로 이어지지 않도록 로그만 남김
        logger.warning(
            f"분석 결과 저장/캐시 실패: {analysis_type}, 오류: {str(e)}",
            exc_info=True
        )


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
        
        analyzed_at = timezone.now().isoformat()
        summary = {
            'news_total_articles': news_result.get('total_articles', 0),
            'sns_total_posts': sns_result.get('total_posts', 0),
            'news_keywords_count': len(news_result.get('top_keywords', [])),
            'sns_keywords_count': len(sns_result.get('top_keywords', []))
        }
        result_payload = {
            'status': 'success',
            'news': news_result,
            'sns': sns_result,
            'summary': summary,
            'analyzed_at': analyzed_at
        }
        _store_and_cache_result(
            analysis_type='keywords',
            result_payload=result_payload,
            parameters={'days': days, 'top_n': top_n},
            platform='both',
            days=days,
            summary=summary
        )
        return result_payload
        
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
        
        analyzed_at = timezone.now().isoformat()
        result_payload = {
            'status': 'success',
            'result': result,
            'analyzed_at': analyzed_at
        }
        _store_and_cache_result(
            analysis_type='compare_platforms',
            result_payload=result_payload,
            parameters={'days': days, 'top_n': top_n, 'min_frequency': min_frequency},
            platform='both',
            days=days,
            summary=result.get('summary', {})
        )
        return result_payload
        
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
        
        updated_at = timezone.now().isoformat()
        summary = {
            'news_keywords_count': len(news_result.get('top_keywords', [])),
            'sns_keywords_count': len(sns_result.get('top_keywords', [])),
            'common_keywords_count': len(common_keywords)
        }
        result_payload = {
            'status': 'success',
            'news_hot_keywords': news_result['top_keywords'],
            'sns_hot_keywords': sns_result['top_keywords'],
            'common_keywords': common_keywords,
            'summary': summary,
            'updated_at': updated_at
        }
        _store_and_cache_result(
            analysis_type='hot_keywords',
            result_payload=result_payload,
            parameters={'days': days, 'top_n': top_n},
            platform='both',
            days=days,
            summary=summary
        )
        return result_payload
        
    except Exception as e:
        logger.error(f"인기 키워드 업데이트 실패: {str(e)}", exc_info=True)
        return {
            'status': 'error',
            'error': str(e),
            'updated_at': timezone.now().isoformat()
        }


@shared_task(name='analyzer.analyze_time_lag_task')
def analyze_time_lag_task(
    days: int = 7,
    top_n: int = 50,
    min_frequency: float = 0.001
):
    """
    뉴스와 SNS 간의 키워드 전파 패턴(시간차)을 분석하는 Celery 작업
    
    Args:
        days: 최근 며칠간의 데이터를 분석할지 (기본값: 7)
        top_n: 상위 N개 키워드만 분석 (기본값: 50)
        min_frequency: 최소 상대 빈도 (기본값: 0.001 = 0.1%)
        
    Returns:
        시간차 분석 결과 딕셔너리
    """
    try:
        logger.info(
            f"시간차 분석 작업 시작: "
            f"최근 {days}일간, 상위 {top_n}개, 최소 빈도 {min_frequency}"
        )
        
        result = analyze_time_lag(
            keywords=None,
            days=days,
            min_frequency=min_frequency,
            top_n=top_n
        )
        
        statistics = result.get('statistics', {})
        logger.info(
            f"시간차 분석 완료: "
            f"총 {statistics.get('total_keywords', 0)}개 키워드 분석"
        )
        
        analyzed_at = timezone.now().isoformat()
        result_payload = {
            'status': 'success',
            'result': result,
            'analyzed_at': analyzed_at
        }
        _store_and_cache_result(
            analysis_type='time_lag',
            result_payload=result_payload,
            parameters={
                'days': days,
                'top_n': top_n,
                'min_frequency': min_frequency
            },
            platform='both',
            days=days,
            summary=result.get('statistics', {})
        )
        return result_payload
        
    except Exception as e:
        logger.error(f"시간차 분석 작업 실패: {str(e)}", exc_info=True)
        return {
            'status': 'error',
            'error': str(e),
            'analyzed_at': timezone.now().isoformat()
        }


@shared_task(name='analyzer.detect_surge_keywords_task')
def detect_surge_keywords_task(
    platform: str = 'both',
    days: int = 7,
    interval_hours: int = 6,
    surge_threshold: float = 2.0,
    min_frequency: float = 0.001,
    top_n: Optional[int] = None
):
    """
    플랫폼별 급상승 키워드를 탐지하는 Celery 작업
    
    Args:
        platform: 분석할 플랫폼 ('news', 'sns', 'both', 기본값: 'both')
        days: 최근 며칠간의 데이터를 분석할지 (기본값: 7)
        interval_hours: 시간대별 집계 간격 (시간 단위, 기본값: 6)
        surge_threshold: 급상승 임계값 (이전 시간대 대비 배수, 기본값: 2.0)
        min_frequency: 최소 상대 빈도 (기본값: 0.001 = 0.1%)
        top_n: 상위 N개 급상승 키워드만 반환 (None이면 전체)
        
    Returns:
        급상승 키워드 탐지 결과 딕셔너리
    """
    try:
        logger.info(
            f"급상승 키워드 탐지 작업 시작: "
            f"플랫폼={platform}, 최근 {days}일간, 임계값={surge_threshold}배"
        )
        
        result = detect_surge_keywords(
            platform=platform,
            days=days,
            interval_hours=interval_hours,
            surge_threshold=surge_threshold,
            min_frequency=min_frequency,
            top_n=top_n
        )
        
        summary = result.get('summary', {})
        logger.info(
            f"급상승 키워드 탐지 완료: "
            f"뉴스 {summary.get('news_surge_count', 0)}개, "
            f"SNS {summary.get('sns_surge_count', 0)}개"
        )
        
        analyzed_at = timezone.now().isoformat()
        result_payload = {
            'status': 'success',
            'result': result,
            'analyzed_at': analyzed_at
        }
        _store_and_cache_result(
            analysis_type='surge_keywords',
            result_payload=result_payload,
            parameters={
                'platform': platform,
                'days': days,
                'interval_hours': interval_hours,
                'surge_threshold': surge_threshold,
                'min_frequency': min_frequency,
                'top_n': top_n
            },
            platform=platform,
            days=days,
            summary=result.get('summary', {})
        )
        return result_payload
        
    except Exception as e:
        logger.error(f"급상승 키워드 탐지 작업 실패: {str(e)}", exc_info=True)
        return {
            'status': 'error',
            'error': str(e),
            'analyzed_at': timezone.now().isoformat()
        }


@shared_task(name='analyzer.analyze_trend_synchronization_task')
def analyze_trend_synchronization_task(
    days: int = 7,
    interval_hours: int = 6,
    min_frequency: float = 0.001,
    top_n: Optional[int] = None
):
    """
    뉴스와 SNS의 트렌드 동기화 정도를 분석하는 Celery 작업
    
    Args:
        days: 최근 며칠간의 데이터를 분석할지 (기본값: 7)
        interval_hours: 시간대별 집계 간격 (시간 단위, 기본값: 6)
        min_frequency: 최소 상대 빈도 (기본값: 0.001 = 0.1%)
        top_n: 상위 N개 키워드만 반환 (None이면 전체)
        
    Returns:
        트렌드 동기화 분석 결과 딕셔너리
    """
    try:
        logger.info(
            f"트렌드 동기화 분석 작업 시작: "
            f"최근 {days}일간, 간격 {interval_hours}시간"
        )
        
        result = analyze_trend_synchronization(
            days=days,
            interval_hours=interval_hours,
            min_frequency=min_frequency,
            top_n=top_n
        )
        
        summary = result.get('summary', {})
        logger.info(
            f"트렌드 동기화 분석 완료: "
            f"동기화 {summary.get('synchronized_count', 0)}개, "
            f"비동기화 {summary.get('desynchronized_count', 0)}개, "
            f"평균 상관관계 {summary.get('avg_correlation', 0):.3f}"
        )
        
        analyzed_at = timezone.now().isoformat()
        result_payload = {
            'status': 'success',
            'result': result,
            'analyzed_at': analyzed_at
        }
        _store_and_cache_result(
            analysis_type='trend_synchronization',
            result_payload=result_payload,
            parameters={
                'days': days,
                'interval_hours': interval_hours,
                'min_frequency': min_frequency,
                'top_n': top_n
            },
            platform='both',
            days=days,
            summary=result.get('summary', {})
        )
        return result_payload
        
    except Exception as e:
        logger.error(f"트렌드 동기화 분석 작업 실패: {str(e)}", exc_info=True)
        return {
            'status': 'error',
            'error': str(e),
            'analyzed_at': timezone.now().isoformat()
        }


@shared_task(name='analyzer.analyze_hourly_trends_task')
def analyze_hourly_trends_task(
    platform: str = 'both',
    days: int = 7,
    min_frequency: float = 0.001,
    top_n: Optional[int] = None
):
    """
    시간대별 트렌드 변화를 분석하는 Celery 작업
    
    Args:
        platform: 분석할 플랫폼 ('news', 'sns', 'both', 기본값: 'both')
        days: 최근 며칠간의 데이터를 분석할지 (기본값: 7)
        min_frequency: 최소 상대 빈도 (기본값: 0.001 = 0.1%)
        top_n: 시간대별 상위 N개 키워드만 반환 (None이면 전체)
        
    Returns:
        시간대별 트렌드 분석 결과 딕셔너리
    """
    try:
        logger.info(
            f"시간대별 트렌드 분석 작업 시작: "
            f"플랫폼={platform}, 최근 {days}일간"
        )
        
        result = analyze_hourly_trends(
            platform=platform,
            days=days,
            min_frequency=min_frequency,
            top_n=top_n
        )
        
        summary = result.get('summary', {})
        logger.info(
            f"시간대별 트렌드 분석 완료: "
            f"뉴스 {summary.get('news_hours_analyzed', 0)}시간대, "
            f"SNS {summary.get('sns_hours_analyzed', 0)}시간대"
        )
        
        analyzed_at = timezone.now().isoformat()
        result_payload = {
            'status': 'success',
            'result': result,
            'analyzed_at': analyzed_at
        }
        _store_and_cache_result(
            analysis_type='hourly_trends',
            result_payload=result_payload,
            parameters={
                'platform': platform,
                'days': days,
                'min_frequency': min_frequency,
                'top_n': top_n
            },
            platform=platform,
            days=days,
            summary=result.get('summary', {})
        )
        return result_payload
        
    except Exception as e:
        logger.error(f"시간대별 트렌드 분석 작업 실패: {str(e)}", exc_info=True)
        return {
            'status': 'error',
            'error': str(e),
            'analyzed_at': timezone.now().isoformat()
        }


@shared_task(name='analyzer.get_keyword_occurrence_times_task')
def get_keyword_occurrence_times_task(
    keyword: str,
    platform: str,
    days: int = 7
):
    """
    특정 키워드가 특정 플랫폼에서 등장한 시간 정보를 추출하는 Celery 작업
    
    Args:
        keyword: 찾을 키워드
        platform: 'news' 또는 'sns'
        days: 최근 며칠간의 데이터를 검색할지 (기본값: 7)
        
    Returns:
        키워드 등장 시간 정보 딕셔너리
    """
    try:
        logger.info(
            f"키워드 등장 시간 추출 작업 시작: "
            f"키워드={keyword}, 플랫폼={platform}, 최근 {days}일간"
        )
        
        result = get_keyword_occurrence_times(
            keyword=keyword,
            platform=platform,
            days=days
        )
        
        logger.info(
            f"키워드 등장 시간 추출 완료: "
            f"등장 횟수 {result.get('occurrence_count', 0)}회"
        )
        
        first_occurrence = result.get('first_occurrence')
        last_occurrence = result.get('last_occurrence')
        
        analyzed_at = timezone.now().isoformat()
        result_payload = {
            'status': 'success',
            'result': {
                'first_occurrence': (
                    first_occurrence.isoformat()
                    if first_occurrence else None
                ),
                'last_occurrence': (
                    last_occurrence.isoformat()
                    if last_occurrence else None
                ),
                'occurrence_count': result.get('occurrence_count', 0),
                'all_times': [
                    t.isoformat() for t in result.get('all_times', [])
                ]
            },
            'analyzed_at': analyzed_at
        }
        _store_and_cache_result(
            analysis_type='keyword_occurrence_times',
            result_payload=result_payload,
            parameters={'keyword': keyword, 'platform': platform, 'days': days},
            platform=platform,
            days=days,
            summary={'occurrence_count': result.get('occurrence_count', 0)}
        )
        return result_payload
        
    except Exception as e:
        logger.error(f"키워드 등장 시간 추출 작업 실패: {str(e)}", exc_info=True)
        return {
            'status': 'error',
            'error': str(e),
            'analyzed_at': timezone.now().isoformat()
        }


@shared_task(name='analyzer.get_keyword_timeline_task')
def get_keyword_timeline_task(
    keyword: str,
    days: int = 7,
    interval_hours: int = 6
):
    """
    키워드의 시간대별 등장 빈도를 계산하여 타임라인 데이터를 생성하는 Celery 작업
    
    Args:
        keyword: 분석할 키워드
        days: 최근 며칠간의 데이터를 분석할지 (기본값: 7)
        interval_hours: 시간대별 집계 간격 (시간 단위, 기본값: 6)
        
    Returns:
        키워드 타임라인 데이터 딕셔너리
    """
    try:
        logger.info(
            f"키워드 타임라인 생성 작업 시작: "
            f"키워드={keyword}, 최근 {days}일간, 간격 {interval_hours}시간"
        )
        
        result = get_keyword_timeline(
            keyword=keyword,
            days=days,
            interval_hours=interval_hours
        )
        
        logger.info(
            f"키워드 타임라인 생성 완료: "
            f"시간대 버킷 {len(result.get('time_labels', []))}개"
        )
        
        analyzed_at = timezone.now().isoformat()
        result_payload = {
            'status': 'success',
            'result': result,
            'analyzed_at': analyzed_at
        }
        _store_and_cache_result(
            analysis_type='keyword_timeline',
            result_payload=result_payload,
            parameters={
                'keyword': keyword,
                'days': days,
                'interval_hours': interval_hours
            },
            platform='both',
            days=days,
            summary={'time_buckets': len(result.get('time_labels', []))}
        )
        return result_payload
        
    except Exception as e:
        logger.error(f"키워드 타임라인 생성 작업 실패: {str(e)}", exc_info=True)
        return {
            'status': 'error',
            'error': str(e),
            'analyzed_at': timezone.now().isoformat()
        }


@shared_task(name='analyzer.get_multiple_keywords_timeline_task')
def get_multiple_keywords_timeline_task(
    keywords: List[str],
    days: int = 7,
    interval_hours: int = 6
):
    """
    여러 키워드의 타임라인 데이터를 한 번에 생성하는 Celery 작업
    
    Args:
        keywords: 분석할 키워드 리스트
        days: 최근 며칠간의 데이터를 분석할지 (기본값: 7)
        interval_hours: 시간대별 집계 간격 (시간 단위, 기본값: 6)
        
    Returns:
        여러 키워드 타임라인 데이터 딕셔너리
    """
    try:
        logger.info(
            f"여러 키워드 타임라인 생성 작업 시작: "
            f"키워드 {len(keywords)}개, 최근 {days}일간, 간격 {interval_hours}시간"
        )
        
        result = get_multiple_keywords_timeline(
            keywords=keywords,
            days=days,
            interval_hours=interval_hours
        )
        
        logger.info(
            f"여러 키워드 타임라인 생성 완료: "
            f"타임라인 {len(result.get('timelines', {}))}개"
        )
        
        analyzed_at = timezone.now().isoformat()
        result_payload = {
            'status': 'success',
            'result': result,
            'analyzed_at': analyzed_at
        }
        _store_and_cache_result(
            analysis_type='multiple_keywords_timeline',
            result_payload=result_payload,
            parameters={
                'keywords': keywords,
                'days': days,
                'interval_hours': interval_hours
            },
            platform='both',
            days=days,
            summary={'timeline_count': len(result.get('timelines', {}))}
        )
        return result_payload
        
    except Exception as e:
        logger.error(f"여러 키워드 타임라인 생성 작업 실패: {str(e)}", exc_info=True)
        return {
            'status': 'error',
            'error': str(e),
            'analyzed_at': timezone.now().isoformat()
        }


@shared_task(name='analyzer.analyze_engagement_keywords_task')
def analyze_engagement_keywords_task(
    days: int = 7,
    min_frequency: float = 0.001,
    top_n: Optional[int] = None,
    engagement_weights: Optional[Dict[str, float]] = None
):
    """
    참여도 기반 인기 키워드를 분석하는 Celery 작업
    
    Args:
        days: 최근 며칠간의 데이터를 분석할지 (기본값: 7)
        min_frequency: 최소 상대 빈도 (기본값: 0.001 = 0.1%)
        top_n: 상위 N개 키워드만 반환 (None이면 전체)
        engagement_weights: 참여도 가중치 딕셔너리 (선택적)
        
    Returns:
        참여도 기반 키워드 분석 결과 딕셔너리
    """
    try:
        logger.info(
            f"참여도 기반 키워드 분석 작업 시작: "
            f"최근 {days}일간, 최소 빈도 {min_frequency}"
        )
        
        result = analyze_engagement_keywords(
            days=days,
            min_frequency=min_frequency,
            top_n=top_n,
            engagement_weights=engagement_weights
        )
        
        summary = result.get('summary', {})
        logger.info(
            f"참여도 기반 키워드 분석 완료: "
            f"키워드 {summary.get('total_keywords', 0)}개, "
            f"바이럴 키워드 {summary.get('viral_keywords_count', 0)}개"
        )
        
        analyzed_at = timezone.now().isoformat()
        result_payload = {
            'status': 'success',
            'result': result,
            'analyzed_at': analyzed_at
        }
        _store_and_cache_result(
            analysis_type='engagement_keywords',
            result_payload=result_payload,
            parameters={
                'days': days,
                'min_frequency': min_frequency,
                'top_n': top_n,
                'engagement_weights': engagement_weights
            },
            platform='sns',
            days=days,
            summary=result.get('summary', {})
        )
        return result_payload
        
    except Exception as e:
        logger.error(f"참여도 기반 키워드 분석 작업 실패: {str(e)}", exc_info=True)
        return {
            'status': 'error',
            'error': str(e),
            'analyzed_at': timezone.now().isoformat()
        }
