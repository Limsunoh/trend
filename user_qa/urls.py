from django.urls import include, path
from rest_framework.routers import DefaultRouter

from .views import ConvertToVectorViewSet, QueryHistoryViewSet, RAGQueryViewSet

router = DefaultRouter()
# router.register(r"vectors", VectorDocumentViewSet, basename="vectors")
router.register(r"history", QueryHistoryViewSet, basename="history")
router.register(r"query", RAGQueryViewSet, basename="query")
router.register(r"convert", ConvertToVectorViewSet, basename="convert")

urlpatterns = [
    path("", include(router.urls)),
]
