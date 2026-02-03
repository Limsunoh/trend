"""
분석 결과 저장/캐시 유틸리티

DB에는 분석 이력과 요약을 저장하고,
Redis에는 최신 결과를 캐싱하는 하이브리드 구조를 지원합니다.
"""
import copy
import json
import logging
from datetime import datetime, date, time
from decimal import Decimal
from typing import Any, Dict, Optional

from analyzer.models import TrendAnalysisResult
from common.redis_services import AnalysisCacheService

# 저장 시 리스트 최대 개수 (news/sns/합계 등 각 리스트당)
MAX_LIST_ITEMS_STORED = 15
# analysis_type별 DB 보관 건수 (초과 시 오래된 것 삭제)
RETENTION_PER_ANALYSIS_TYPE = 50


def trim_lists_to_n(obj: Any, n: int = MAX_LIST_ITEMS_STORED) -> Any:
    """
    객체를 재귀 순회하며 리스트는 최대 n개만 남김 (DB/응답 크기 절감).
    news, sns, common_keywords 등 각 리스트에 적용.
    """
    if isinstance(obj, dict):
        return {k: trim_lists_to_n(v, n) for k, v in obj.items()}
    if isinstance(obj, list):
        return [trim_lists_to_n(item, n) for item in obj[:n]]
    return obj


def _retain_latest_per_analysis_type(analysis_type: str, keep: int = RETENTION_PER_ANALYSIS_TYPE) -> None:
    """
    해당 analysis_type의 최신 keep건만 남기고 나머지 행 삭제.
    """
    ids_to_keep = list(
        TrendAnalysisResult.objects.filter(analysis_type=analysis_type)
        .order_by('-created_at')
        .values_list('id', flat=True)[:keep]
    )
    deleted, _ = TrendAnalysisResult.objects.filter(
        analysis_type=analysis_type
    ).exclude(id__in=ids_to_keep).delete()
    if deleted:
        logging.getLogger(__name__).info(
            "Retention: analysis_type=%s, deleted=%s old rows, kept %s",
            analysis_type, deleted, len(ids_to_keep)
        )


def _json_default(value):
    # JSONField에 저장 가능한 타입으로 변환
    if isinstance(value, (datetime, date, time)):
        return value.isoformat()
    if isinstance(value, Decimal):
        return float(value)
    return str(value)


def _make_json_safe(payload: Any) -> Any:
    """
    JSONField 저장을 위해 직렬화 가능한 형태로 변환
    """
    # datetime/decimal 등을 문자열/숫자로 변환해서 JSON dump
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
    분석 결과를 DB에 저장.
    - result/summary 내 리스트는 최대 MAX_LIST_ITEMS_STORED(15)개만 저장.
    - 저장 후 해당 analysis_type은 최신 RETENTION_PER_ANALYSIS_TYPE(50)건만 유지.
    """
    # 리스트 15개로 자른 뒤 JSON 안전 변환
    trimmed_result = trim_lists_to_n(copy.deepcopy(result), MAX_LIST_ITEMS_STORED)
    summary_raw = summary or result.get('summary', {})
    trimmed_summary = trim_lists_to_n(copy.deepcopy(summary_raw), MAX_LIST_ITEMS_STORED)

    safe_result = _make_json_safe(trimmed_result)
    safe_parameters = _make_json_safe(parameters or {})
    safe_summary = _make_json_safe(trimmed_summary)

    row = TrendAnalysisResult.objects.create(
        analysis_type=analysis_type,
        platform=platform,
        days=days,
        status=status,
        error_message=error_message,
        parameters=safe_parameters,
        summary=safe_summary,
        result_data=safe_result
    )
    # analysis_type별 최신 50건만 유지
    _retain_latest_per_analysis_type(analysis_type, RETENTION_PER_ANALYSIS_TYPE)
    return row


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
    # 캐시는 최신 결과만 보관
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
    # 1) Redis 캐시 확인
    cache_service = AnalysisCacheService()
    cached = cache_service.get_latest_result(
        analysis_type=analysis_type,
        platform=platform,
        days=days,
        parameters=parameters
    )
    if cached:
        return cached
    
    # 2) 캐시가 없으면 DB에서 최신 결과 조회
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
    # 3) 다음 요청을 위해 캐시에 저장
    cache_latest_analysis(
        analysis_type=analysis_type,
        result=result,
        parameters=parameters,
        platform=platform,
        days=days
    )
    return result
