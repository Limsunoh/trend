from django.urls import path
from rest_framework.routers import DefaultRouter
from .views import (
    VectorDocumentViewSet,
    QueryHistoryViewSet,
    query,
    convert_to_vector
)

router = DefaultRouter()
router.register(r'vectors', VectorDocumentViewSet, basename='vectordocument')
router.register(r'history', QueryHistoryViewSet, basename='queryhistory')

urlpatterns = [
    path('query/', query, name='query'),
    path('convert/', convert_to_vector, name='convert_to_vector'),
] + router.urls

