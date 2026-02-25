from django.db import models


class QueryHistory(models.Model):
    query_text = models.TextField()
    answer_text = models.TextField()
    sources = models.JSONField(default=list, blank=True)
    top_k = models.PositiveIntegerField(default=5)
    collection = models.CharField(max_length=100, default="trend_docs")
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self) -> str:
        return f"[{self.created_at:%Y-%m-%d %H:%M}] {self.query_text[:30]}"


# VectorDocument는 "나중에 필요할 수도 있다" 했으니
# 지금은 Django가 모델로 인식하지 않도록 완전 제거(주석만) 해둠.
# (주석 블록 내부는 Django가 절대 모델로 등록하지 않음)
"""
class VectorDocument(models.Model):
    pass
"""
