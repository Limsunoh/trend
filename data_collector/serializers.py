from rest_framework import serializers
from .models import NewsSource, NewsArticle, SocialMediaPost, DataCollectionJob


class NewsSourceSerializer(serializers.ModelSerializer):
    """뉴스 소스 Serializer"""
    # TODO: Meta 클래스 정의
    pass


class NewsArticleSerializer(serializers.ModelSerializer):
    """뉴스 기사 Serializer"""
    # TODO: Meta 클래스 정의
    pass


class SocialMediaPostSerializer(serializers.ModelSerializer):
    """소셜 미디어 게시물 Serializer"""
    # TODO: Meta 클래스 정의
    pass


class DataCollectionJobSerializer(serializers.ModelSerializer):
    """데이터 수집 작업 Serializer"""
    # TODO: Meta 클래스 정의
    pass
