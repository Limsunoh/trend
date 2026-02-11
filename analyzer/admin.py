from django.contrib import admin

from .models import TrendAnalysisResult


@admin.register(TrendAnalysisResult)
class TrendAnalysisResultAdmin(admin.ModelAdmin):
    list_display = ("analysis_type", "platform", "days", "status", "created_at")
    list_filter = ("analysis_type", "platform", "status")
    search_fields = ("analysis_type",)
