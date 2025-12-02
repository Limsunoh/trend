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
# ViewSet 등록
# 각 ViewSet은 자동으로 CRUD 엔드포인트를 생성합니다.
router.register(r'sources', NewsSourceViewSet, basename='source')
router.register(r'news', NewsArticleViewSet, basename='news')
router.register(r'social', SocialMediaPostViewSet, basename='social')
router.register(r'jobs', DataCollectionJobViewSet, basename='job')

urlpatterns = [
    # 경향신문 RSS 수집 트리거 엔드포인트
    # POST /api/collect/trigger/ - 수집 작업 시작
    # GET /api/collect/trigger/ - 최근 수집 작업 상태 조회
    path('trigger/', trigger_collection, name='trigger_collection'),
] + router.urls
