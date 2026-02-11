"""
대시보드 API URL 설정

뉴스 기사·소셜 미디어 게시물만 등록합니다.
"""

from django.urls import include, path
from rest_framework.routers import DefaultRouter

from .views import NewsArticleViewSet, SocialMediaPostViewSet

router = DefaultRouter()
router.register(r"news", NewsArticleViewSet, basename="news-article")
router.register(r"social", SocialMediaPostViewSet, basename="social-post")

urlpatterns = [
    path("", include(router.urls)),
]
