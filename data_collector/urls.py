from django.urls import path
from rest_framework.routers import DefaultRouter
from .views import (
    NewsSourceViewSet,
    NewsArticleViewSet,
    SocialMediaPostViewSet,
    DataCollectionJobViewSet,
    trigger_collection
)

router = DefaultRouter()
# TODO: ViewSet 등록
# router.register(r'sources', NewsSourceViewSet)
# router.register(r'news', NewsArticleViewSet)
# router.register(r'social', SocialMediaPostViewSet)
# router.register(r'jobs', DataCollectionJobViewSet)

urlpatterns = [
    # TODO: URL 패턴 추가
    # path('trigger/', trigger_collection, name='trigger_collection'),
] + router.urls
