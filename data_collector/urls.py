from rest_framework.routers import DefaultRouter
from django.urls import path
from .views import (
    NewsSourceCreateCSVViewSet,
    NewsSourceCreateViewSet,
    # NewsSourceViewSet, NewsArticleViewSet, SocialMediaPostViewSet, SocialMediaSourceViewSet는
    # dashboard/views.py로 이동했습니다.
    DataCollectionJobViewSet,
    NewsArticleCollectionViewSet,
    SocialMediaCollectionViewSet,
    AllCollectionViewSet,
    ThumbnailProxyView
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
# NewsSourceViewSet, NewsArticleViewSet, SocialMediaPostViewSet, SocialMediaSourceViewSet는
# dashboard/views.py로 이동하여 dashboard/urls.py에 등록되었습니다.
router.register(r'jobs', DataCollectionJobViewSet, basename='job')
router.register(
    r'all-collection/trigger',
    AllCollectionViewSet,
    basename='all-collection-trigger'
)
router.register(
    r'news-collection/trigger',
    NewsArticleCollectionViewSet,
    basename='news-collection-trigger'
)
router.register(
    r'social-collection/trigger',
    SocialMediaCollectionViewSet,
    basename='social-collection-trigger'
)

# 이미지 프록시 엔드포인트 (router 외부)
urlpatterns = router.urls + [
    path('thumbnail-proxy/', ThumbnailProxyView.as_view(), name='thumbnail-proxy'),
]
