from celery import shared_task


@shared_task
def collect_news_task():
    """뉴스 데이터 수집 작업"""
    # TODO: 뉴스 수집 로직 구현
    pass


@shared_task
def collect_social_media_task():
    """소셜 미디어 데이터 수집 작업"""
    # TODO: 소셜 미디어 수집 로직 구현
    pass
