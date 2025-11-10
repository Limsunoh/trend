from celery import shared_task


@shared_task
def analyze_keywords_task():
    """키워드 분석 작업"""
    # TODO: 키워드 분석 로직 구현
    pass


@shared_task
def analyze_topics_task():
    """토픽 분석 작업"""
    # TODO: 토픽 분석 로직 구현
    pass


@shared_task
def update_hot_keywords():
    """실시간 인기 키워드 업데이트"""
    # TODO: 인기 키워드 업데이트 로직 구현
    pass
