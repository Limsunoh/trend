from rest_framework.routers import DefaultRouter
from .views import (
    NewsSourceCreateCSVViewSet,
    NewsSourceCreateViewSet,
    NewsSourceViewSet,
    NewsArticleViewSet,
    SocialMediaPostViewSet,
    DataCollectionJobViewSet,
    NewsArticleCollectionViewSet,
    SocialMediaCollectionViewSet,
    AllCollectionViewSet
)

router = DefaultRouter()
# ViewSet 등록
# 각 ViewSet은 자동으로 CRUD 엔드포인트를 생성합니다.
router.register(
    'news-source-csv',
    NewsSourceCreateCSVViewSet,
    basename='news-source-csv'
)
router.register(
    r'sources/create-from-rss',
    NewsSourceCreateViewSet,
    basename='rss-source-create'
)
router.register(r'sources', NewsSourceViewSet, basename='source')
router.register(r'news', NewsArticleViewSet, basename='news')
router.register(r'social', SocialMediaPostViewSet, basename='social')
router.register(r'jobs', DataCollectionJobViewSet, basename='job')
router.register(
    r'all-collection/trigger',
    AllCollectionViewSet,
    basename='all-collection-trigger'
)
router.register(
    r'news-article-collection/trigger',
    NewsArticleCollectionViewSet,
    basename='news-article-collection-trigger'
)
router.register(
    r'social-media-collection/trigger',
    SocialMediaCollectionViewSet,
    basename='social-media-collection-trigger'
)

urlpatterns = router.urls
