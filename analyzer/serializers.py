from rest_framework import serializers
from .models import Keyword, Topic, TrendAnalysis, HotKeyword


class KeywordSerializer(serializers.ModelSerializer):
    """키워드 Serializer"""
    # TODO: Meta 클래스 정의
    pass


class TopicSerializer(serializers.ModelSerializer):
    """토픽 Serializer"""
    # TODO: Meta 클래스 정의
    pass


class TrendAnalysisSerializer(serializers.ModelSerializer):
    """트렌드 분석 Serializer"""
    # TODO: Meta 클래스 정의
    pass


class HotKeywordSerializer(serializers.ModelSerializer):
    """인기 키워드 Serializer"""
    # TODO: Meta 클래스 정의
    pass
