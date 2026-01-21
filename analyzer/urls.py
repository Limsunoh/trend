from rest_framework.routers import DefaultRouter
from .views import TrendAnalysisResultViewSet

router = DefaultRouter()
router.register(r'analysis-results', TrendAnalysisResultViewSet)

urlpatterns = router.urls
