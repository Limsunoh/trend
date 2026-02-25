from rest_framework import serializers
from .models import QueryHistory


# ====== Model Serializers ======
# class VectorDocumentSerializer(serializers.ModelSerializer):
#     class Meta:
#         model = VectorDocument
#         fields = ["id", "embedding_id", "doc_type", "source_url", "metadata", "created_at"]
#         read_only_fields = ["id", "created_at"]


class QueryHistorySerializer(serializers.ModelSerializer):
    class Meta:
        model = QueryHistory
        fields = [
            "id",
            "query_text",
            "answer_text",
            "sources",
            "top_k",
            "collection",
            "created_at",
        ]
        read_only_fields = ["id", "created_at"]


class QueryRequestSerializer(serializers.Serializer):
    query = serializers.CharField()
    top_k = serializers.IntegerField(required=False, default=5, min_value=1, max_value=50)
    include_sources = serializers.BooleanField(required=False, default=True)

    # ✅ (선택) LLM 기반 라우터: 질문 의도/검색 키워드를 한 번에 판별
    # - intent(뉴스/소셜/혼합) + entity + search_query를 LLM 한 번 호출로 생성
    # - 기본값 False (비용 절감)
    use_intent_router = serializers.BooleanField(required=False, default=False)

    # LLM 옵션(선택)
    model = serializers.CharField(required=False, allow_blank=True, default="")
    temperature = serializers.FloatField(required=False, allow_null=True, default=None)
    max_output_tokens = serializers.IntegerField(required=False, allow_null=True, default=None)
    reasoning_effort = serializers.CharField(required=False, allow_blank=True, default="")
    instructions = serializers.CharField(required=False, allow_blank=True, default="")
    force_refresh = serializers.BooleanField(required=False, default=False)

    def validate_temperature(self, value):
        # 빈값/None OK
        if value is None:
            return None
        # 0도 허용(=결정적 출력 의도)
        if value < 0 or value > 2:
            raise serializers.ValidationError("temperature는 0~2 범위여야 합니다.")
        return float(value)

    def validate_max_output_tokens(self, value):
        # None/빈값 OK
        if value is None:
            return None
        # 사용자가 0을 보내면 '기본값 사용'으로 처리
        if int(value) == 0:
            return None
        # OpenAI 최소 제한 방어(최소 16)
        if int(value) < 16:
            return 16
        return int(value)

    def validate(self, attrs):
        # model 빈 문자열이면 None처럼 처리
        if attrs.get("model", "") == "":
            attrs["model"] = None

        # reasoning_effort 빈 문자열이면 None처럼 처리
        if attrs.get("reasoning_effort", "") == "":
            attrs["reasoning_effort"] = None

        # instructions 빈 문자열이면 None처럼 처리
        if attrs.get("instructions", "") == "":
            attrs["instructions"] = None

        return attrs


class SourceSerializer(serializers.Serializer):
    id = serializers.CharField()
    distance = serializers.FloatField()
    url = serializers.CharField(required=False, allow_blank=True, allow_null=True)
    type = serializers.CharField(required=False, allow_null=True)
    platform = serializers.CharField(required=False, allow_null=True)
    publisher = serializers.CharField(required=False, allow_null=True)
    category = serializers.CharField(required=False, allow_null=True)
    identifier = serializers.CharField(required=False, allow_null=True)
    source_display = serializers.CharField(required=False, allow_null=True)
    published_at = serializers.CharField(required=False, allow_null=True)
    excerpt = serializers.CharField(required=False, allow_blank=True, allow_null=True)


class QueryResponseSerializer(serializers.Serializer):
    query = serializers.CharField()
    answer = serializers.CharField()
    history_id = serializers.IntegerField(allow_null=True, required=False)
    sources = serializers.ListField(child=serializers.DictField(), required=False)
    model = serializers.CharField(required=False, allow_blank=True)
