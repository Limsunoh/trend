from rest_framework import serializers

# TODO: QueryHistory, VectorDocument 모델 사용


class VectorDocumentSerializer(serializers.ModelSerializer):
    """벡터 문서 Serializer"""

    # TODO: Meta 클래스 정의
    pass


class QueryHistorySerializer(serializers.ModelSerializer):
    """질의응답 히스토리 Serializer"""

    # TODO: Meta 클래스 정의
    pass


class QueryRequestSerializer(serializers.Serializer):
    """질의 요청 Serializer"""

    # TODO: 필드 정의
    pass


class QueryResponseSerializer(serializers.Serializer):
    """질의 응답 Serializer"""

    # TODO: 필드 정의
    pass
