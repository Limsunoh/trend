from rest_framework import viewsets
from .models import TrendAnalysisResult
from .serializers import TrendAnalysisResultSerializer


class TrendAnalysisResultViewSet(viewsets.ReadOnlyModelViewSet):
    """트렌드 분석 결과 ViewSet"""
    queryset = TrendAnalysisResult.objects.all()
    serializer_class = TrendAnalysisResultSerializer
