from celery import shared_task
from common.redis_services import (
    DuplicatePreventionService,
    RateLimitService,
    RealtimeStatsService
)


@shared_task
def collect_news_task():
    """
    뉴스 데이터 수집 작업
    - 우선순위 2: 중복 데이터 수집 방지
    - 우선순위 4: API Rate Limiting
    - 우선순위 5: 실시간 통계 집계
    """
    duplicate_check = DuplicatePreventionService()
    rate_limit = RateLimitService()
    stats = RealtimeStatsService()
    
    # TODO: 뉴스 소스 목록 가져오기
    news_sources = []  # TODO: 실제 소스 목록
    
    for source in news_sources:
        # 우선순위 4: Rate Limit 체크
        api_key = source.get('api_key', 'default')
        limit_check = rate_limit.check_rate_limit(
            identifier=api_key,
            max_requests=100,  # TODO: 설정에서 가져오기
            window_seconds=3600
        )
        
        if not limit_check['allowed']:
            # Rate limit 초과 시 다음 소스로
            continue
        
        # TODO: 뉴스 기사 목록 가져오기
        articles = []  # TODO: 실제 API 호출
        
        for article in articles:
            article_url = article.get('url')
            
            # 우선순위 2: 중복 체크
            if duplicate_check.is_already_collected('news', article_url):
                continue
            
            # TODO: 기사 수집 및 저장
            # article_data = fetch_article(article_url)
            # NewsArticle.objects.create(...)
            
            # 우선순위 2: 수집 완료 표시
            duplicate_check.mark_as_collected('news', article_url)
            
            # 우선순위 5: 통계 업데이트
            stats.increment_counter('articles_collected')
            stats.record_timestamp('article_collected')


@shared_task
def collect_social_media_task():
    """
    소셜 미디어 데이터 수집 작업
    - 우선순위 2: 중복 데이터 수집 방지
    - 우선순위 4: API Rate Limiting
    - 우선순위 5: 실시간 통계 집계
    """
    duplicate_check = DuplicatePreventionService()
    rate_limit = RateLimitService()
    stats = RealtimeStatsService()
    
    # TODO: 소셜 미디어 플랫폼별 수집
    platforms = ['twitter', 'facebook']  # TODO: 설정에서 가져오기
    
    for platform in platforms:
        # 우선순위 4: Rate Limit 체크
        api_key = f"{platform}_api_key"  # TODO: 실제 API 키
        limit_check = rate_limit.check_rate_limit(
            identifier=api_key,
            max_requests=100,  # TODO: 플랫폼별 제한
            window_seconds=3600
        )
        
        if not limit_check['allowed']:
            continue
        
        # TODO: 소셜 미디어 게시물 가져오기
        posts = []  # TODO: 실제 API 호출
        
        for post in posts:
            post_id = post.get('id')
            
            # 우선순위 2: 중복 체크
            if duplicate_check.is_already_collected(platform, post_id):
                continue
            
            # TODO: 게시물 수집 및 저장
            # SocialMediaPost.objects.create(...)
            
            # 우선순위 2: 수집 완료 표시
            duplicate_check.mark_as_collected(platform, post_id)
            
            # 우선순위 5: 통계 업데이트
            stats.increment_counter(f'{platform}_posts_collected')
            stats.record_timestamp(f'{platform}_post_collected')
