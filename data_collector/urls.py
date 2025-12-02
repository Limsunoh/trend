from rest_framework.routers import DefaultRouter
from .views import (
    RSSSourceCreationViewSet,
    NewsSourceViewSet,
    NewsArticleViewSet,
    SocialMediaPostViewSet,
    DataCollectionJobViewSet,
    TriggerCollectionViewSet
)

router = DefaultRouter()
# ViewSet 등록
# 각 ViewSet은 자동으로 CRUD 엔드포인트를 생성합니다.
router.register(
    r'sources/create-from-rss',
    RSSSourceCreationViewSet,
    basename='rss-source-creation'
)
router.register(r'sources', NewsSourceViewSet, basename='source')
router.register(r'news', NewsArticleViewSet, basename='news')
router.register(r'social', SocialMediaPostViewSet, basename='social')
router.register(r'jobs', DataCollectionJobViewSet, basename='job')
router.register(
    r'trigger',
    TriggerCollectionViewSet,
    basename='trigger'
)

urlpatterns = router.urls
