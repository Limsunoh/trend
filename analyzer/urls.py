from django.urls import path
from rest_framework.routers import DefaultRouter
from .views import (
    KeywordViewSet,
    TopicViewSet,
    TrendAnalysisViewSet,
    HotKeywordViewSet,
    analyze_trends
)

router = DefaultRouter()
# TODO: ViewSet 등록
# router.register(r'keywords', KeywordViewSet)
# router.register(r'topics', TopicViewSet)
# router.register(r'analyses', TrendAnalysisViewSet)
# router.register(r'hot-keywords', HotKeywordViewSet)

urlpatterns = [
    # TODO: URL 패턴 추가
    # path('analyze/', analyze_trends, name='analyze_trends'),
] + router.urls
