# TrendAnalysisResultViewSet와 각 분석 타입별 ViewSet는
# dashboard/views.py로 이동하여 dashboard/urls.py에 등록되었습니다.

from rest_framework.routers import DefaultRouter

router = DefaultRouter()
# analyzer 앱의 ViewSet은 모두 dashboard로 이동했습니다.

urlpatterns = router.urls
