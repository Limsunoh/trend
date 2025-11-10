from django.urls import path
from .views import (
    dashboard_overview,
    trending_keywords,
    trending_topics,
    realtime_stats,
    keyword_detail,
    topic_detail
)

urlpatterns = [
    path('overview/', dashboard_overview, name='dashboard_overview'),
    path('trending/keywords/', trending_keywords, name='trending_keywords'),
    path('trending/topics/', trending_topics, name='trending_topics'),
    path('realtime/stats/', realtime_stats, name='realtime_stats'),
    path('keywords/<int:keyword_id>/', keyword_detail, name='keyword_detail'),
    path('topics/<int:topic_id>/', topic_detail, name='topic_detail'),
]

