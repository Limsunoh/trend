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
    # 경향신문 RSS 수집 트리거 엔드포인트
    # POST /api/collect/trigger/ - 수집 작업 시작
    # GET /api/collect/trigger/ - 최근 수집 작업 상태 조회
    path('trigger/', trigger_collection, name='trigger_collection'),
] + router.urls
