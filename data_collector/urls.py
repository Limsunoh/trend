from django.urls import path
from rest_framework.routers import DefaultRouter

from .views import (
    AllCollectionViewSet,
    DataCollectionJobViewSet,
    NewsArticleCollectionViewSet,
    NewsSourceCreateCSVViewSet,
    NewsSourceCreateViewSet,
    NewsSourceViewSet,
    SocialMediaCollectionViewSet,
    SocialMediaSourceViewSet,
    ThumbnailProxyView,
)

router = DefaultRouter()

# 뉴스 소스 / 소셜 미디어 소스 (목록·상세 조회)
router.register(r"sources", NewsSourceViewSet, basename="news-source")
router.register(r"social-sources", SocialMediaSourceViewSet, basename="social-source")

# ViewSet 등록
router.register(
    "news-source-csv", NewsSourceCreateCSVViewSet, basename="news-source-csv"
)
router.register(
    r"sources/create-from-rss", NewsSourceCreateViewSet, basename="rss-source-create"
)
router.register(r"jobs", DataCollectionJobViewSet, basename="job")
router.register(
    r"all-collection/trigger", AllCollectionViewSet, basename="all-collection-trigger"
)
router.register(
    r"news-collection/trigger",
    NewsArticleCollectionViewSet,
    basename="news-collection-trigger",
)
router.register(
    r"social-collection/trigger",
    SocialMediaCollectionViewSet,
    basename="social-collection-trigger",
)

# 이미지 프록시 엔드포인트 (router 외부)
urlpatterns = router.urls + [
    path("thumbnail-proxy/", ThumbnailProxyView.as_view(), name="thumbnail-proxy"),
]
