from rest_framework.routers import DefaultRouter
from django.urls import path, include
from .views import (
    # Data Collector ViewSets
    NewsSourceViewSet,
    NewsArticleViewSet,
    SocialMediaPostViewSet,
    SocialMediaSourceViewSet,
    # Analyzer ViewSets
    TrendAnalysisResultViewSet,
    KeywordsAnalysisViewSet,
    ComparePlatformsAnalysisViewSet,
    HotKeywordsAnalysisViewSet,
    TimeLagAnalysisViewSet,
    SurgeKeywordsAnalysisViewSet,
    TrendSynchronizationAnalysisViewSet,
    HourlyTrendsAnalysisViewSet,
    KeywordOccurrenceTimesAnalysisViewSet,
    KeywordTimelineAnalysisViewSet,
    MultipleKeywordsTimelineAnalysisViewSet,
    EngagementKeywordsAnalysisViewSet,
)

router = DefaultRouter()

# Data Collector ViewSets
router.register(r'sources', NewsSourceViewSet, basename='news-source')
router.register(r'news', NewsArticleViewSet, basename='news-article')
router.register(r'social', SocialMediaPostViewSet, basename='social-post')
router.register(r'social-sources', SocialMediaSourceViewSet, basename='social-source')

# Analyzer ViewSets - 전체 목록 조회용
router.register(r'analysis-results', TrendAnalysisResultViewSet, basename='analysis-result')

# Analyzer ViewSets - 각 분석 타입별 (URL 경로 기반)
# 기본 경로 (platform, days 없음)
router.register(
    r'analysis/keywords',
    KeywordsAnalysisViewSet,
    basename='keywords-analysis'
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
    r'analysis/time-lag',
    TimeLagAnalysisViewSet,
    basename='time-lag-analysis'
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
    r'analysis/keyword-occurrence-times',
    KeywordOccurrenceTimesAnalysisViewSet,
    basename='keyword-occurrence-times-analysis'
)
router.register(
    r'analysis/keyword-timeline',
    KeywordTimelineAnalysisViewSet,
    basename='keyword-timeline-analysis'
)
router.register(
    r'analysis/multiple-keywords-timeline',
    MultipleKeywordsTimelineAnalysisViewSet,
    basename='multiple-keywords-timeline-analysis'
)
router.register(
    r'analysis/engagement-keywords',
    EngagementKeywordsAnalysisViewSet,
    basename='engagement-keywords-analysis'
)

urlpatterns = [
    # Router URLs (기본 경로들)
    path('', include(router.urls)),
]

