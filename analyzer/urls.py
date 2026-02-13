"""
분석 결과 API URL 설정
"""
from rest_framework.routers import DefaultRouter
from django.urls import path, include
from .views import (
    TrendAnalysisResultViewSet,
    KeywordsAnalysisViewSet,
    ComparePlatformsAnalysisViewSet,
    HotKeywordsAnalysisViewSet,
    TimeLagAnalysisViewSet,
    SurgeKeywordsAnalysisViewSet,
    TrendSynchronizationAnalysisViewSet,
    HourlyTrendsAnalysisViewSet,
    EngagementKeywordsAnalysisViewSet,
)

router = DefaultRouter()

router.register(
    r'analysis-results', TrendAnalysisResultViewSet, basename='analysis-result'
)
router.register(
    r'analysis/keywords', KeywordsAnalysisViewSet, basename='keywords-analysis'
)
router.register(
    r'analysis/compare-platforms',
    ComparePlatformsAnalysisViewSet,
    basename='compare-platforms-analysis'
)
router.register(
    r'analysis/hot-keywords',
    HotKeywordsAnalysisViewSet,
    basename='hot-keywords-analysis'
)
router.register(
    r'analysis/time-lag', TimeLagAnalysisViewSet, basename='time-lag-analysis'
)
router.register(
    r'analysis/surge-keywords',
    SurgeKeywordsAnalysisViewSet,
    basename='surge-keywords-analysis'
)
router.register(
    r'analysis/trend-synchronization',
    TrendSynchronizationAnalysisViewSet,
    basename='trend-synchronization-analysis'
)
router.register(
    r'analysis/hourly-trends',
    HourlyTrendsAnalysisViewSet,
    basename='hourly-trends-analysis'
)
router.register(
    r'analysis/engagement-keywords',
    EngagementKeywordsAnalysisViewSet,
    basename='engagement-keywords-analysis'
)

urlpatterns = [
    path('', include(router.urls)),
]
