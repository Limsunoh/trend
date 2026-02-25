"""
Redis 활용 서비스 모음. 모두 RedisService 상속, self.client로 Redis 접근.

1. DuplicatePreventionService: 뉴스/SNS 등 수집 데이터 중복 방지 (키 존재 여부만 저장, 7일 TTL)
2. SearchCacheService: 대시보드 검색 결과 캐싱 (파라미터 해시 키, 5분 TTL)
3. RealtimeStatsService: 실시간 카운터·이벤트 타임스탬프·시간대별 통계 (24시간 TTL)
4. RAGCacheService: RAG(LLM) 질의응답 결과 캐싱 (쿼리 해시 키, 24시간 TTL)
5. RateLimitService: 식별자(IP/API키 등)별 요청 횟수 제한 (TTL 윈도우)
6. AnalysisCacheService: 분석 결과 최신값 캐시 (DB 이력 + Redis 최신 하이브리드)
"""

import hashlib
import json
from datetime import datetime, timedelta
from typing import Any, Dict, Optional

import redis
from django.conf import settings


class RedisService:
    """Redis 기본 클래스. 상속 후 self.client로 Redis 접근."""

    def __init__(self):
        """
        settings의 REDIS_HOST, REDIS_PORT, REDIS_DB로 연결.
        decode_responses=True로 문자열 반환.
        """
        self.client = redis.Redis(
            host=settings.REDIS_HOST,
            port=int(settings.REDIS_PORT),
            db=int(settings.REDIS_DB),
            decode_responses=True,
        )


# ============================================
# 1. 중복 데이터 수집 방지
# ============================================
class DuplicatePreventionService(RedisService):
    """
    수집 데이터 중복 방지. URL·게시물 ID 등으로 키를 만들어 존재 여부만 저장.
    키 형식: collected:{source}:{identifier}. 7일 TTL 후 자동 삭제.
    """

    def __init__(self):
        super().__init__()
        self.DUPLICATE_PREFIX = "collected:"
        self.TTL_DAYS = 7
        self.TTL_SECONDS = self.TTL_DAYS * 24 * 3600

    def is_already_collected(self, source: str, identifier: str) -> bool:
        """이미 수집된 데이터면 True. Redis EXISTS로 키 존재 여부만 확인."""
        key = f"{self.DUPLICATE_PREFIX}{source}:{identifier}"
        return self.client.exists(key) > 0

    def mark_as_collected(self, source: str, identifier: str):
        """수집 완료 표시. SETEX로 값 "1"과 TTL을 함께 저장 (실제 값은 불필요, 존재만 중요)."""
        key = f"{self.DUPLICATE_PREFIX}{source}:{identifier}"
        self.client.setex(key, self.TTL_SECONDS, "1")

    def get_collected_count(self, source: str) -> int:
        """특정 소스의 수집된 데이터 개수. KEYS 패턴으로 조회 (키가 많으면 부하 주의)."""
        pattern = f"{self.DUPLICATE_PREFIX}{source}:*"
        keys = self.client.keys(pattern)
        return len(keys)


# ============================================
# 2. 검색 결과 캐싱 (대시보드)
# ============================================
class SearchCacheService(RedisService):
    """
    대시보드 검색 결과 캐싱. 동일 검색 조건 반복 DB 쿼리 방지.
    키: search:{search_type}:{params MD5 해시}. TTL 5분.
    """

    def __init__(self):
        super().__init__()
        self.SEARCH_PREFIX = "search:"
        self.CACHE_TTL = 300

    def get_cache_key(self, search_type: str, params: Dict) -> str:
        """검색 타입 + 파라미터(JSON sort_keys)를 MD5 해시로 캐시 키 생성. 파라미터 순서 달라도 동일 키."""
        params_str = json.dumps(params, sort_keys=True)
        params_hash = hashlib.md5(params_str.encode()).hexdigest()
        return f"{self.SEARCH_PREFIX}{search_type}:{params_hash}"

    def get_cached_results(self, search_type: str, params: Dict) -> Optional[Dict]:
        """캐시된 검색 결과 딕셔너리 반환. 없거나 만료 시 None."""
        cache_key = self.get_cache_key(search_type, params)
        cached = self.client.get(cache_key)
        if cached:
            return json.loads(cached)
        return None

    def cache_results(self, search_type: str, params: Dict, results: Dict):
        """검색 결과를 JSON으로 저장. SETEX로 TTL(5분)과 함께 저장."""
        cache_key = self.get_cache_key(search_type, params)
        self.client.setex(
            cache_key, self.CACHE_TTL, json.dumps(results, ensure_ascii=False)
        )

    def invalidate_search_cache(self, search_type: str):
        """해당 search_type의 캐시 키를 모두 삭제. KEYS 패턴 사용 (키 많으면 부하 주의)."""
        pattern = f"{self.SEARCH_PREFIX}{search_type}:*"
        keys = self.client.keys(pattern)
        if keys:
            self.client.delete(*keys)


# 3. 실시간 통계 집계
class RealtimeStatsService(RedisService):
    """
    실시간 통계: 카운터(INCRBY), 이벤트 타임스탬프(List), 시간대별 카운터.
    키 접두사 stats:. TTL 24시간. 이벤트 리스트는 최근 1000개만 유지(LTRIM).
    """

    def __init__(self):
        super().__init__()
        self.STATS_PREFIX = "stats:"
        self.TTL_SECONDS = 24 * 3600

    def increment_counter(self, metric_name: str, value: int = 1):
        """메트릭 카운터를 value만큼 증가. INCRBY(원자적). TTL 24시간."""
        key = f"{self.STATS_PREFIX}counter:{metric_name}"
        self.client.incrby(key, value)
        self.client.expire(key, self.TTL_SECONDS)

    def record_timestamp(self, event_name: str):
        """이벤트 발생 시점(ISO 문자열)을 리스트 앞에 추가. LPUSH 후 LTRIM으로 최근 1000개만 유지, TTL 24시간."""
        key = f"{self.STATS_PREFIX}events:{event_name}"
        timestamp = datetime.now().isoformat()
        self.client.lpush(key, timestamp)
        self.client.ltrim(key, 0, 999)
        self.client.expire(key, self.TTL_SECONDS)

    def get_counter(self, metric_name: str) -> int:
        """메트릭 현재 카운터 값. 없으면 0."""
        key = f"{self.STATS_PREFIX}counter:{metric_name}"
        value = self.client.get(key)
        return int(value) if value else 0

    def get_recent_events(self, event_name: str, limit: int = 100) -> list:
        """최근 이벤트 타임스탬프 리스트(최신 순). LRANGE로 앞에서 limit개."""
        key = f"{self.STATS_PREFIX}events:{event_name}"
        return self.client.lrange(key, 0, limit - 1)

    def increment_hourly_counter(self, metric_name: str, value: int = 1):
        """현재 시각의 시간대(0–23)별 카운터 증가. 키: stats:hourly:{metric_name}:{hour}. INCRBY, TTL 24시간."""
        now = datetime.now()
        hourly_key = f"{self.STATS_PREFIX}hourly:{metric_name}:{now.hour}"
        self.client.incrby(hourly_key, value)
        self.client.expire(hourly_key, self.TTL_SECONDS)

    def get_hourly_stats(self, metric_name: str) -> Dict:
        """현재 시간대의 카운트 조회. Returns: {'hour': 0-23, 'count': int}."""
        now = datetime.now()
        hourly_key = f"{self.STATS_PREFIX}hourly:{metric_name}:{now.hour}"
        count = self.client.get(hourly_key)
        return {"hour": now.hour, "count": int(count) if count else 0}


# 4. RAG 질의응답 캐싱
class RAGCacheService(RedisService):
    """
    RAG(LLM) 질의응답 결과 캐싱. 동일 질문 재호출 시 LLM 호출 생략.
    쿼리 정규화(lower, strip) 후 MD5 해시로 키 생성. TTL 24시간.
    """

    def __init__(self):
        super().__init__()
        self.CACHE_PREFIX = "rag:query:"
        self.CACHE_TTL = 24 * 3600

    def get_cache_key(self, query: str) -> str:
        """쿼리 정규화(lower, strip) 후 MD5 해시로 캐시 키 생성. 유사 질문 동일 키."""
        normalized = query.lower().strip()

        # 컨텍스트 정보를 캐시 키에 포함
        # 동일 쿼리라도 top_k, include_sources 등이 다르면 다른 캐시 키 생성
        if cache_context:
            context_str = json.dumps(cache_context, sort_keys=True)
            normalized = f"{normalized}:{context_str}"

        # MD5 해시를 사용하여 고정 길이 키 생성
        query_hash = hashlib.md5(normalized.encode()).hexdigest()

        return f"{self.CACHE_PREFIX}{query_hash}"
    
    def get_cached_response(self, query: str, cache_context: Optional[Dict] = None) -> Optional[Dict]:
        """
        캐시된 답변 조회

        Redis에서 해당 쿼리의 캐시된 응답을 조회합니다.
        캐시가 없거나 만료된 경우 None을 반환합니다.

        Args:
            query: 사용자 질의 텍스트
            cache_context: 캐시 키에 포함할 컨텍스트 (top_k, include_sources 등)

        Returns:
            캐시된 응답 딕셔너리 또는 None
        """
        # 쿼리와 컨텍스트를 기반으로 캐시 키 생성
        cache_key = self.get_cache_key(query, cache_context)

        # Redis에서 값 조회
        cached = self.client.get(cache_key)

        if cached:
            return json.loads(cached)

        return None
    
    def cache_response(self, query: str, response: Dict, ttl: Optional[int] = None, cache_context: Optional[Dict] = None):
        """
        RAG 응답 캐싱

        LLM으로 생성한 응답을 Redis에 저장합니다.
        SETEX 명령어를 사용하여 키와 함께 TTL(Time To Live)을 설정합니다.

        Args:
            query: 사용자 질의 텍스트
            response: LLM 응답 딕셔너리 (예: {'answer': '...', 'sources': [...]})
            ttl: 캐시 유지 시간(초). None이면 기본값(24시간) 사용
            cache_context: 캐시 키에 포함할 컨텍스트 (top_k, include_sources 등)
        """
        # 캐시 키 생성 (컨텍스트 포함)
        cache_key = self.get_cache_key(query, cache_context)

        # TTL 설정 (지정하지 않으면 기본값 사용)
        ttl = ttl or self.CACHE_TTL

        # Redis에 저장
        self.client.setex(
            cache_key,
            ttl,
            json.dumps(response, ensure_ascii=False)
        )
    
    def invalidate_cache(self, query: str):
        """해당 쿼리의 캐시만 삭제. 갱신이 필요할 때 사용."""
        cache_key = self.get_cache_key(query)
        self.client.delete(cache_key)


# 5. API Rate Limiting (외부 API 호출 제한)
class RateLimitService(RedisService):
    """
    식별자(IP, API키, 사용자 ID 등)별 요청 횟수 제한.
    기본 100회/1시간. check_rate_limit 호출 시 max_requests, window_seconds로 오버라이드 가능.
    키: ratelimit:{identifier}. 첫 요청 시 SETEX, 이후 INCR. TTL 지나면 자동 리셋.
    """

    def __init__(self):
        super().__init__()
        self.RATE_LIMIT_PREFIX = "ratelimit:"
        self.DEFAULT_MAX_REQUESTS = 100
        self.DEFAULT_WINDOW_SECONDS = 3600

    def check_rate_limit(
        self,
        identifier: str,
        max_requests: Optional[int] = None,
        window_seconds: Optional[int] = None,
    ) -> Dict[str, Any]:
        """
        허용 여부 확인 후 허용이면 카운터 증가.
        Args:
            identifier: 식별자 (IP, API키 등)
            max_requests: 윈도우 내 최대 요청 수 (None이면 기본 100)
            window_seconds: 윈도우 크기 초 (None이면 기본 3600)
        Returns:
            allowed, remaining, reset_at, limit
        """
        max_requests = max_requests or self.DEFAULT_MAX_REQUESTS
        window_seconds = window_seconds or self.DEFAULT_WINDOW_SECONDS
        key = f"{self.RATE_LIMIT_PREFIX}{identifier}"
        current = self.client.get(key)
        current_count = int(current) if current else 0

        if current_count >= max_requests:
            ttl = self.client.ttl(key)
            reset_at = datetime.now() + timedelta(seconds=ttl)
            return {
                "allowed": False,
                "remaining": 0,
                "reset_at": reset_at,
                "limit": max_requests,
            }

        if current_count == 0:
            self.client.setex(key, window_seconds, 1)
        else:
            self.client.incr(key)
        remaining = max_requests - (current_count + 1)
        reset_at = datetime.now() + timedelta(seconds=window_seconds)
        return {
            "allowed": True,
            "remaining": remaining,
            "reset_at": reset_at,
            "limit": max_requests,
        }

    def get_rate_limit_status(self, identifier: str) -> Dict:
        """카운터 증가 없이 현재 상태만 조회. Returns: current(현재 요청 수), reset_in_seconds(리셋까지 초)."""
        key = f"{self.RATE_LIMIT_PREFIX}{identifier}"
        current = self.client.get(key)
        ttl = self.client.ttl(key)
        return {
            "current": int(current) if current else 0,
            "reset_in_seconds": ttl if ttl > 0 else 0,
        }


# 6. 분석 결과 최신 캐시
class AnalysisCacheService(RedisService):
    """
    분석 결과 최신값 캐시. DB에는 이력/요약, Redis에는 최신 결과 전체 저장하는 하이브리드.
    TTL은 settings.ANALYSIS_CACHE_TTL_SECONDS (기본 6시간).
    """

    def __init__(self):
        super().__init__()
        self.ANALYSIS_PREFIX = "analysis:latest:"
        self.CACHE_TTL = int(getattr(settings, "ANALYSIS_CACHE_TTL_SECONDS", 6 * 3600))

    def get_cache_key(
        self,
        analysis_type: str,
        platform: Optional[str] = None,
        days: Optional[int] = None,
        parameters: Optional[Dict[str, Any]] = None,
    ) -> str:
        """analysis_type, platform, days, parameters를 JSON 해시로 캐시 키 생성."""
        params = {"analysis_type": analysis_type, "platform": platform, "days": days}
        if parameters:
            params.update(parameters)

        params_str = json.dumps(params, sort_keys=True, default=str)
        params_hash = hashlib.md5(params_str.encode()).hexdigest()
        return f"{self.ANALYSIS_PREFIX}{analysis_type}:{params_hash}"

    def get_latest_result(
        self,
        analysis_type: str,
        platform: Optional[str] = None,
        days: Optional[int] = None,
        parameters: Optional[Dict[str, Any]] = None,
    ) -> Optional[Dict[str, Any]]:
        """캐시된 최신 분석 결과 딕셔너리 반환. 없거나 만료 시 None."""
        cache_key = self.get_cache_key(analysis_type, platform, days, parameters)
        cached = self.client.get(cache_key)
        if cached:
            return json.loads(cached)
        return None

    def set_latest_result(
        self,
        analysis_type: str,
        result: Dict[str, Any],
        platform: Optional[str] = None,
        days: Optional[int] = None,
        parameters: Optional[Dict[str, Any]] = None,
        ttl: Optional[int] = None,
    ):
        """분석 결과를 JSON으로 저장. ttl 미지정 시 settings 기준 TTL(기본 6시간)."""
        cache_key = self.get_cache_key(analysis_type, platform, days, parameters)
        ttl = ttl or self.CACHE_TTL
        self.client.setex(
            cache_key, ttl, json.dumps(result, ensure_ascii=False, default=str)
        )
