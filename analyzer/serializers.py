from rest_framework import serializers
from .models import TrendAnalysisResult


class TrendAnalysisResultSerializer(serializers.ModelSerializer):
    """트렌드 분석 결과 Serializer"""
    class Meta:
        model = TrendAnalysisResult
        fields = '__all__'
