from django.db import models


class TrendAnalysisResult(models.Model):
    """트렌드 분석 결과 저장 (하이브리드: DB 이력 + Redis 최신 캐시)"""
    analysis_type = models.CharField(max_length=50, db_index=True)
    platform = models.CharField(
        max_length=10,
        null=True,
        blank=True,
        db_index=True
    )
    days = models.IntegerField(null=True, blank=True, db_index=True)
    status = models.CharField(max_length=20, default='success', db_index=True)
    error_message = models.TextField(null=True, blank=True)
    parameters = models.JSONField(default=dict, blank=True)
    summary = models.JSONField(default=dict, blank=True)
    result_data = models.JSONField(default=dict, blank=True)
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)

    class Meta:
        indexes = [
            models.Index(fields=['analysis_type', 'platform', 'days']),
            models.Index(fields=['analysis_type', 'created_at'])
        ]
        ordering = ['-created_at']

    def __str__(self):
        return f"{self.analysis_type} ({self.created_at:%Y-%m-%d %H:%M:%S})"
