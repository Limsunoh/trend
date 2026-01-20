"""
분석 결과 저장/캐시 유틸리티

DB에는 분석 이력과 요약을 저장하고,
Redis에는 최신 결과를 캐싱하는 하이브리드 구조를 지원합니다.
"""
import json
from datetime import datetime, date, time
from decimal import Decimal
from typing import Any, Dict, Optional

from analyzer.models import TrendAnalysisResult
from common.redis_services import AnalysisCacheService


def _json_default(value):
    if isinstance(value, (datetime, date, time)):
        return value.isoformat()
    if isinstance(value, Decimal):
        return float(value)
    return str(value)


def _make_json_safe(payload: Any) -> Any:
    """
    JSONField 저장을 위해 직렬화 가능한 형태로 변환
    """
    return json.loads(json.dumps(payload, default=_json_default, ensure_ascii=False))


def store_analysis_result(
    analysis_type: str,
    result: Dict[str, Any],
    parameters: Optional[Dict[str, Any]] = None,
    platform: Optional[str] = None,
    days: Optional[int] = None,
    status: str = 'success',
    error_message: Optional[str] = None,
    summary: Optional[Dict[str, Any]] = None
) -> TrendAnalysisResult:
    """
    분석 결과를 DB에 저장
    """
    safe_result = _make_json_safe(result)
    safe_parameters = _make_json_safe(parameters or {})
    safe_summary = _make_json_safe(summary or result.get('summary', {}))
    
    return TrendAnalysisResult.objects.create(
        analysis_type=analysis_type,
        platform=platform,
        days=days,
        status=status,
        error_message=error_message,
        parameters=safe_parameters,
        summary=safe_summary,
        result_data=safe_result
    )


def cache_latest_analysis(
    analysis_type: str,
    result: Dict[str, Any],
    parameters: Optional[Dict[str, Any]] = None,
    platform: Optional[str] = None,
    days: Optional[int] = None,
    ttl: Optional[int] = None
):
    """
    최신 분석 결과를 Redis에 캐싱
    """
    cache_service = AnalysisCacheService()
    safe_result = _make_json_safe(result)
    cache_service.set_latest_result(
        analysis_type=analysis_type,
        result=safe_result,
        platform=platform,
        days=days,
        parameters=parameters,
        ttl=ttl
    )


def get_latest_analysis(
    analysis_type: str,
    parameters: Optional[Dict[str, Any]] = None,
    platform: Optional[str] = None,
    days: Optional[int] = None
) -> Optional[Dict[str, Any]]:
    """
    최신 분석 결과 조회 (Redis -> DB fallback)
    """
    cache_service = AnalysisCacheService()
    cached = cache_service.get_latest_result(
        analysis_type=analysis_type,
        platform=platform,
        days=days,
        parameters=parameters
    )
    if cached:
        return cached
    
    queryset = TrendAnalysisResult.objects.filter(
        analysis_type=analysis_type
    )
    if platform is not None:
        queryset = queryset.filter(platform=platform)
    if days is not None:
        queryset = queryset.filter(days=days)
    
    latest = queryset.order_by('-created_at').first()
    if not latest:
        return None
    
    result = latest.result_data
    cache_latest_analysis(
        analysis_type=analysis_type,
        result=result,
        parameters=parameters,
        platform=platform,
        days=days
    )
    return result
