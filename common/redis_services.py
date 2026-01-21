"""
Redis 활용 서비스 모음

이 모듈은 프로젝트에서 사용하는 6가지 주요 Redis 서비스를 제공합니다:
1. 중복 데이터 수집 방지 - 이미 수집한 데이터를 추적하여 중복 방지
2. 검색 결과 캐싱 - 대시보드 검색 결과를 캐싱하여 성능 향상
3. 실시간 통계 집계 - 실시간 카운터 및 이벤트 추적
4. RAG 질의응답 캐싱 - LLM 응답 결과를 캐싱하여 비용 절감
5. API Rate Limiting - 외부 API 호출 제한 관리
6. 분석 결과 최신 캐시 - 분석 결과를 빠르게 제공

모든 서비스는 RedisService 기본 클래스를 상속받아 Redis 연결을 공유합니다.
"""
import json
import hashlib
from datetime import datetime, timedelta
from typing import Optional, Dict, Any
from django.conf import settings
import redis


class RedisService:
    """
    Redis 기본 서비스 클래스
    
    모든 Redis 서비스의 기본 클래스로, 공통 Redis 연결을 제공합니다.
    각 서비스는 이 클래스를 상속받아 self.client를 통해 Redis에 접근합니다.
    
    사용 예시:
        class MyService(RedisService):
            def __init__(self):
                super().__init__()  # Redis 연결 초기화
                # 이제 self.client를 사용할 수 있습니다
    """
    
    def __init__(self):
        """
        Redis 연결 초기화
        
        settings.py에서 다음 설정값을 읽어옵니다:
        - REDIS_HOST: Redis 서버 호스트 (기본값: 'localhost')
        - REDIS_PORT: Redis 서버 포트 (기본값: '6379')
        - REDIS_DB: 사용할 Redis 데이터베이스 번호 (기본값: '0')
        
        decode_responses=True 옵션으로 문자열 응답을 자동으로 디코딩합니다.
        """
        self.client = redis.Redis(
            host=settings.REDIS_HOST,
            port=int(settings.REDIS_PORT),
            db=int(settings.REDIS_DB),
            decode_responses=True  # 응답을 자동으로 문자열로 변환
        )


# ============================================
# 1. 중복 데이터 수집 방지
# ============================================
class DuplicatePreventionService(RedisService):
    """
    중복 데이터 수집 방지 서비스
    
    뉴스 기사, 소셜 미디어 게시물 등 데이터 수집 시
    이미 수집한 데이터를 추적하여 중복 수집을 방지합니다.
    
    동작 원리:
    - 각 데이터에 대해 고유 식별자(URL, 게시물 ID 등)를 키로 사용
    - 수집 완료 시 Redis에 표시를 남김
    - 다음 수집 시 해당 키가 존재하는지 확인
    
    특징:
    - TTL(Time To Live)을 사용하여 7일 후 자동 삭제
    - 메모리 효율적: 실제 데이터는 저장하지 않고 존재 여부만 표시
    - 빠른 조회: O(1) 시간 복잡도
    
    사용 예시:
        duplicate_check = DuplicatePreventionService()
        
        # 중복 체크
        if duplicate_check.is_already_collected('news', article_url):
            continue  # 이미 수집했으므로 스킵
        
        # 데이터 수집
        article = fetch_article(article_url)
        save_to_db(article)
        
        # 수집 완료 표시
        duplicate_check.mark_as_collected('news', article_url)
    """
    
    def __init__(self):
        """
        중복 방지 서비스 초기화
        
        Redis 연결을 설정하고, 키 접두사와 TTL을 설정합니다.
        """
        super().__init__()  # Redis 연결 초기화
        self.DUPLICATE_PREFIX = "collected:"  # Redis 키 접두사
        self.TTL_DAYS = 7  # 7일 후 자동 삭제 (메모리 절약)
        self.TTL_SECONDS = self.TTL_DAYS * 24 * 3600  # 604800초 (7일)
    
    def is_already_collected(self, source: str, identifier: str) -> bool:
        """
        이미 수집된 데이터인지 확인
        
        Redis에서 해당 데이터의 수집 여부를 확인합니다.
        EXISTS 명령어를 사용하여 키 존재 여부만 확인합니다.
        
        Args:
            source: 데이터 소스 타입 ('news', 'twitter', 'facebook' 등)
            identifier: 데이터 고유 식별자 (URL, 게시물 ID 등)
            
        Returns:
            True: 이미 수집됨, False: 아직 수집 안 됨
            
        Redis 키 형식:
            "collected:news:https://example.com/article/123"
            "collected:twitter:1234567890"
            
        시간 복잡도:
            O(1) - Redis EXISTS 명령어는 매우 빠름
            
        예시:
            if duplicate_check.is_already_collected('news', article_url):
                print("이미 수집한 기사입니다")
                return
        """
        # Redis 키 생성
        # 형식: "collected:{source}:{identifier}"
        key = f"{self.DUPLICATE_PREFIX}{source}:{identifier}"
        
        # EXISTS 명령어로 키 존재 여부 확인
        # 반환값: 키가 존재하면 1, 없으면 0
        # > 0 비교로 boolean으로 변환
        return self.client.exists(key) > 0
    
    def mark_as_collected(self, source: str, identifier: str):
        """
        수집 완료 표시
        
        데이터 수집이 완료되었음을 Redis에 기록합니다.
        SETEX 명령어를 사용하여 TTL과 함께 저장합니다.
        
        Args:
            source: 데이터 소스 타입
            identifier: 데이터 고유 식별자
            
        동작:
            1. Redis 키 생성
            2. SETEX로 저장 (값은 "1"로 설정, 실제로는 존재 여부만 중요)
               TTL은 __init__에서 미리 계산된 self.TTL_SECONDS 사용
            
        TTL 설정 이유:
            - 오래된 데이터는 자동으로 삭제하여 메모리 절약
            - 7일 후에는 다시 수집 가능 (데이터 업데이트 고려)
            
        예시:
            # 기사 수집 완료 후
            duplicate_check.mark_as_collected('news', article_url)
            # 이제 is_already_collected()는 True를 반환
        """
        # Redis 키 생성
        key = f"{self.DUPLICATE_PREFIX}{source}:{identifier}"
        
        # SETEX: 키와 값, TTL을 함께 설정
        # 값은 "1"로 설정 (실제 값은 중요하지 않음, 존재 여부만 중요)
        # TTL이 지나면 자동으로 삭제됨
        # TTL은 __init__에서 미리 계산된 self.TTL_SECONDS 사용
        self.client.setex(key, self.TTL_SECONDS, "1")
    
    def get_collected_count(self, source: str) -> int:
        """
        수집된 데이터 개수 조회
        
        특정 소스에서 수집한 데이터의 총 개수를 반환합니다.
        KEYS 명령어를 사용하여 패턴 매칭으로 키를 찾습니다.
        
        Args:
            source: 데이터 소스 타입
            
        Returns:
            수집된 데이터 개수
            
        주의사항:
            - KEYS 명령어는 프로덕션 환경에서 주의해서 사용
            - 대량의 키가 있으면 성능에 영향을 줄 수 있음
            - 필요시 SCAN 명령어로 대체 고려
            
        예시:
            count = duplicate_check.get_collected_count('news')
            print(f"오늘 수집한 뉴스 기사: {count}개")
        """
        # 패턴 생성: "collected:news:*"
        # *는 와일드카드로 모든 키를 매칭
        pattern = f"{self.DUPLICATE_PREFIX}{source}:*"
        
        # KEYS 명령어로 패턴에 맞는 모든 키 조회
        # 반환값: 키 이름 리스트
        keys = self.client.keys(pattern)
        
        # 리스트 길이가 수집된 데이터 개수
        return len(keys)


# ============================================
# 2. 검색 결과 캐싱 (대시보드)
# ============================================
class SearchCacheService(RedisService):
    """
    검색 결과 캐싱 서비스
    
    대시보드의 검색 결과(키워드, 토픽 등)를 캐싱하여
    동일한 검색 조건에 대한 반복적인 DB 쿼리를 방지합니다.
    
    주요 기능:
    - 검색 파라미터를 해시화하여 캐시 키 생성
    - 캐시된 검색 결과 조회
    - 새로운 검색 결과 캐싱
    - 특정 타입의 검색 캐시 일괄 무효화
    
    캐시 전략:
    - 기본 TTL: 5분 (300초)
    - 파라미터 기반 키 생성으로 다양한 검색 조건 지원
    - 검색 타입별 캐시 관리
    
    사용 예시:
        cache_service = SearchCacheService()
        
        params = {
            'keyword': 'AI',
            'date_from': '2024-01-01',
            'limit': 100
        }
        
        # 캐시 확인
        cached = cache_service.get_cached_results('keyword_search', params)
        if cached:
            return cached
        
        # DB 쿼리 실행
        results = Keyword.objects.filter(...)
        cache_service.cache_results('keyword_search', params, results)
    """
    
    def __init__(self):
        """
        검색 캐싱 서비스 초기화
        
        Redis 연결을 설정하고, 키 접두사와 기본 TTL을 설정합니다.
        """
        super().__init__()  # Redis 연결 초기화
        self.SEARCH_PREFIX = "search:"  # Redis 키 접두사
        self.CACHE_TTL = 300  # 5분 (초 단위)
        # 짧은 TTL을 사용하는 이유:
        # - 검색 결과는 자주 변경될 수 있음
        # - 실시간성과 성능의 균형
        # - 5분이면 대부분의 사용자에게 충분히 빠름
    
    def get_cache_key(self, search_type: str, params: Dict) -> str:
        """
        검색 파라미터 기반 캐시 키 생성
        
        검색 타입과 파라미터를 조합하여 고유한 캐시 키를 생성합니다.
        파라미터 딕셔너리를 JSON으로 변환 후 해시화합니다.
        
        Args:
            search_type: 검색 타입 ('keyword_search', 'topic_search' 등)
            params: 검색 파라미터 딕셔너리
            
        Returns:
            Redis 캐시 키 (예: "search:keyword_search:abc123...")
            
        키 생성 과정:
            1. params를 JSON 문자열로 변환 (sort_keys=True로 순서 보장)
            2. MD5 해시화
            3. search_type과 조합
            
        예시:
            params1 = {'keyword': 'AI', 'limit': 100}
            params2 = {'limit': 100, 'keyword': 'AI'}  # 순서 다름
            # 하지만 sort_keys=True로 인해 동일한 키 생성
            
        주의사항:
            - params에 datetime 객체 등 JSON 직렬화 불가능한 타입이 있으면 오류 발생
            - 필요시 문자열로 변환 후 사용
        """
        # 파라미터를 JSON 문자열로 변환
        # sort_keys=True: 키 순서를 정렬하여 동일한 파라미터는 항상 동일한 문자열 생성
        # 예: {'a': 1, 'b': 2}와 {'b': 2, 'a': 1}이 동일한 JSON 문자열이 됨
        params_str = json.dumps(params, sort_keys=True)
        
        # MD5 해시화
        # 파라미터가 길어도 고정 길이 키 생성
        params_hash = hashlib.md5(params_str.encode()).hexdigest()
        
        # 최종 키 생성
        return f"{self.SEARCH_PREFIX}{search_type}:{params_hash}"
    
    def get_cached_results(self, search_type: str, params: Dict) -> Optional[Dict]:
        """
        캐시된 검색 결과 조회
        
        Redis에서 해당 검색 조건의 캐시된 결과를 조회합니다.
        
        Args:
            search_type: 검색 타입
            params: 검색 파라미터
            
        Returns:
            캐시된 검색 결과 딕셔너리 또는 None
            
        예시:
            params = {'keyword': 'AI', 'limit': 100}
            cached = cache_service.get_cached_results('keyword_search', params)
            if cached:
                return Response(cached)  # DB 쿼리 없이 즉시 반환
        """
        # 캐시 키 생성
        cache_key = self.get_cache_key(search_type, params)
        
        # Redis에서 값 조회
        cached = self.client.get(cache_key)
        
        if cached:
            # JSON 문자열을 딕셔너리로 변환
            return json.loads(cached)
        
        # 캐시가 없는 경우
        return None
    
    def cache_results(self, search_type: str, params: Dict, results: Dict):
        """
        검색 결과 캐싱
        
        DB 쿼리 결과를 Redis에 저장합니다.
        
        Args:
            search_type: 검색 타입
            params: 검색 파라미터
            results: 검색 결과 딕셔너리
            
        저장 과정:
            1. 캐시 키 생성
            2. results를 JSON 문자열로 변환
            3. SETEX로 TTL과 함께 저장
            
        예시:
            # DB 쿼리 실행
            keywords = Keyword.objects.filter(name__icontains='AI')[:100]
            results = {
                'keywords': [{'id': 1, 'name': 'AI'}, ...],
                'total': 100
            }
            
            # 캐싱
            cache_service.cache_results('keyword_search', params, results)
        """
        # 캐시 키 생성
        cache_key = self.get_cache_key(search_type, params)
        
        # SETEX: 키, TTL, 값을 함께 설정
        # ensure_ascii=False: 한글 등 유니코드 문자 보존
        self.client.setex(
            cache_key,
            self.CACHE_TTL,
            json.dumps(results, ensure_ascii=False)
        )
    
    def invalidate_search_cache(self, search_type: str):
        """
        특정 타입의 검색 캐시 일괄 무효화
        
        특정 검색 타입의 모든 캐시를 삭제합니다.
        데이터가 대량 업데이트되어 캐시를 갱신해야 할 때 사용합니다.
        
        Args:
            search_type: 삭제할 검색 타입
            
        동작 과정:
            1. KEYS 명령어로 해당 타입의 모든 키 조회
            2. DELETE 명령어로 일괄 삭제
            
        사용 시나리오:
            - 키워드 데이터가 대량 업데이트된 경우
            - 관리자가 캐시를 수동으로 갱신하고 싶은 경우
            
        예시:
            # 키워드 데이터 업데이트 후
            cache_service.invalidate_search_cache('keyword_search')
            # 다음 검색부터는 새로운 데이터로 조회
            
        주의사항:
            - KEYS 명령어는 대량의 키가 있으면 성능에 영향을 줄 수 있음
            - 프로덕션 환경에서는 SCAN 명령어 사용 고려
        """
        # 패턴 생성: "search:keyword_search:*"
        pattern = f"{self.SEARCH_PREFIX}{search_type}:*"
        
        # KEYS로 패턴에 맞는 모든 키 조회
        keys = self.client.keys(pattern)
        
        if keys:
            # DELETE 명령어로 일괄 삭제
            # *keys: 리스트를 언패킹하여 여러 키를 한 번에 삭제
            self.client.delete(*keys)


# ============================================
# 3. 실시간 통계 집계
# ============================================
class RealtimeStatsService(RedisService):
    """
    실시간 통계 집계 서비스
    
    실시간으로 발생하는 이벤트와 통계를 수집하고 조회합니다.
    대시보드의 실시간 통계 표시에 사용됩니다.
    
    주요 기능:
    - 카운터 증가/조회 (예: 수집한 기사 수)
    - 이벤트 타임스탬프 기록/조회
    - 시간대별 통계 조회
    
    특징:
    - 빠른 쓰기/읽기 성능
    - TTL을 사용한 자동 정리
    - 최근 이벤트만 유지 (메모리 절약)
    
    사용 예시:
        stats = RealtimeStatsService()
        
        # 기사 수집 시
        stats.increment_counter('articles_collected')
        stats.record_timestamp('article_collected')
        
        # 통계 조회
        total = stats.get_counter('articles_collected')
        recent = stats.get_recent_events('article_collected', limit=10)
    """
    
    def __init__(self):
        """
        실시간 통계 서비스 초기화
        
        Redis 연결을 설정하고, 키 접두사를 설정합니다.
        """
        super().__init__()  # Redis 연결 초기화
        self.STATS_PREFIX = "stats:"  # Redis 키 접두사
        self.TTL_SECONDS = 24 * 3600  # 86400초 (24시간)
    
    def increment_counter(self, metric_name: str, value: int = 1):
        """
        카운터 증가
        
        특정 메트릭의 카운터를 증가시킵니다.
        INCRBY 명령어를 사용하여 원자적(atomic) 연산을 보장합니다.
        
        Args:
            metric_name: 메트릭 이름 (예: 'articles_collected', 'tweets_collected')
            value: 증가시킬 값 (기본값: 1)
            
        Redis 키 형식:
            "stats:counter:articles_collected"
            
        원자적 연산:
            - INCRBY는 원자적 연산이므로 동시성 문제 없음
            - 여러 프로세스에서 동시에 호출해도 정확한 카운트 보장
            
        TTL 설정:
            - 24시간 후 자동 삭제
            - 일일 통계만 유지하여 메모리 절약
            
        예시:
            # 기사 수집 완료 시
            stats.increment_counter('articles_collected')
            
            # 여러 개 한 번에 증가
            stats.increment_counter('articles_collected', value=5)
        """
        # Redis 키 생성
        key = f"{self.STATS_PREFIX}counter:{metric_name}"
        
        # INCRBY: 카운터를 value만큼 증가
        # 원자적 연산으로 동시성 문제 없음
        self.client.incrby(key, value)
        
        # TTL 설정: 24시간
        # expire 명령어는 키가 존재할 때만 작동
        # 이미 TTL이 설정되어 있어도 새로 설정 가능
        self.client.expire(key, self.TTL_SECONDS)
        
    
    def record_timestamp(self, event_name: str):
        """
        이벤트 타임스탬프 기록
        
        이벤트 발생 시점을 기록합니다.
        LPUSH 명령어를 사용하여 리스트의 앞에 추가합니다.
        
        Args:
            event_name: 이벤트 이름 (예: 'article_collected', 'tweet_collected')
            
        Redis 키 형식:
            "stats:events:article_collected"
            
        데이터 구조:
            Redis List (리스트)
            - LPUSH로 앞에 추가 (최신 이벤트가 앞에)
            - LRANGE로 조회 시 최신 순서로 반환
            
            
        메모리 관리:
            - LTRIM으로 최근 1000개만 유지
            - 24시간 TTL 설정
            
            
        예시:
            # 기사 수집 완료 시
            stats.record_timestamp('article_collected')
            
            # 나중에 조회
            events = stats.get_recent_events('article_collected', limit=10)
        """
        # Redis 키 생성
        key = f"{self.STATS_PREFIX}events:{event_name}"
        
        # 현재 시간을 ISO 형식 문자열로 변환
        # 예: "2024-01-01T12:00:00.123456"
        timestamp = datetime.now().isoformat()
        
        # LPUSH: 리스트의 앞에 추가 (Left Push)
        # 최신 이벤트가 리스트의 앞에 위치
        self.client.lpush(key, timestamp)
        
        # LTRIM: 리스트를 지정된 범위로 자르기
        # 0부터 999까지 = 최근 1000개만 유지
        # 나머지는 삭제하여 메모리 절약
        self.client.ltrim(key, 0, 999)
        
        # TTL 설정: 24시간
        self.client.expire(key, self.TTL_SECONDS)
    
    def get_counter(self, metric_name: str) -> int:
        """
        카운터 값 조회
        
        특정 메트릭의 현재 카운터 값을 조회합니다.
        
        Args:
            metric_name: 메트릭 이름
            
        Returns:
            카운터 값 (없으면 0)
            
        예시:
            total = stats.get_counter('articles_collected')
            print(f"오늘 수집한 기사: {total}개")
        """
        # Redis 키 생성
        key = f"{self.STATS_PREFIX}counter:{metric_name}"
        
        # GET으로 값 조회
        value = self.client.get(key)
        
        # 값이 있으면 정수로 변환, 없으면 0 반환
        return int(value) if value else 0
    
    def get_recent_events(self, event_name: str, limit: int = 100) -> list:
        """
        최근 이벤트 조회
        
        특정 이벤트의 최근 발생 기록을 조회합니다.
        LRANGE 명령어를 사용하여 리스트에서 조회합니다.
        
        Args:
            event_name: 이벤트 이름
            limit: 조회할 최대 개수 (기본값: 100)
            
        Returns:
            이벤트 타임스탬프 리스트 (최신 순서)
            
        데이터 구조:
            Redis List에서 0부터 limit-1까지 조회
            (최신 이벤트가 앞에 있으므로 최신 순서)
            
        예시:
            events = stats.get_recent_events('article_collected', limit=10)
            for event in events:
                print(f"이벤트 발생: {event}")
        """
        # Redis 키 생성
        key = f"{self.STATS_PREFIX}events:{event_name}"
        
        # LRANGE: 리스트에서 범위 조회
        # 0부터 limit-1까지 = 최신 limit개
        events = self.client.lrange(key, 0, limit - 1)
        
        # 이벤트는 이미 문자열(ISO 형식)이므로 그대로 반환
        return events
    
    def increment_hourly_counter(self, metric_name: str, value: int = 1):
        """
        시간대별 카운터 증가
        
        특정 메트릭의 현재 시간대별 카운터를 증가시킵니다.
        INCRBY 명령어를 사용하여 원자적(atomic) 연산을 보장합니다.
        
        Args:
            metric_name: 메트릭 이름 (예: 'articles_collected', 'tweets_collected')
            value: 증가시킬 값 (기본값: 1)
            
        Redis 키 형식:
            "stats:hourly:articles_collected:14"  # 14시(오후 2시)
            
        원자적 연산:
            - INCRBY는 원자적 연산이므로 동시성 문제 없음
            - 여러 프로세스에서 동시에 호출해도 정확한 카운트 보장
            
        TTL 설정:
            - 24시간 후 자동 삭제
            - 일일 통계만 유지하여 메모리 절약
            
        사용 예시:
            # 기사 수집 완료 시 (현재 시간대 카운터 증가)
            stats.increment_hourly_counter('articles_collected')
            
            # 여러 개 한 번에 증가
            stats.increment_hourly_counter('articles_collected', value=5)
            
        주의사항:
            - 현재 시간대의 카운터만 증가
            - 시간이 바뀌면 새로운 시간대 키가 생성됨
        """
        # 현재 시간 객체
        now = datetime.now()
        
        # 시간대별 키 생성
        # 형식: "stats:hourly:{metric_name}:{hour}"
        hourly_key = f"{self.STATS_PREFIX}hourly:{metric_name}:{now.hour}"
        
        # INCRBY: 카운터를 value만큼 증가
        # 원자적 연산으로 동시성 문제 없음
        self.client.incrby(hourly_key, value)
        
        # TTL 설정: 24시간
        # expire 명령어는 키가 존재할 때만 작동
        # 이미 TTL이 설정되어 있어도 새로 설정 가능
        self.client.expire(hourly_key, self.TTL_SECONDS)
    
    def get_hourly_stats(self, metric_name: str) -> Dict:
        """
        시간대별 통계 조회
        
        현재 시간대의 통계를 조회합니다.
        시간대별로 별도의 키를 사용하여 집계합니다.
        
        Args:
            metric_name: 메트릭 이름
            
        Returns:
            {
                'hour': int,    # 현재 시간 (0-23)
                'count': int    # 해당 시간대의 카운트
            }
            
        Redis 키 형식:
            "stats:hourly:articles_collected:14"  # 14시(오후 2시)
            
        사용 목적:
            - 시간대별 트래픽 분석
            - 피크 시간대 파악
            
        예시:
            hourly = stats.get_hourly_stats('articles_collected')
            print(f"{hourly['hour']}시에 {hourly['count']}개 수집")
            
        주의사항:
            - 현재는 현재 시간대만 조회
            - 과거 시간대 조회 기능은 별도 구현 필요
        """
        # 현재 시간 객체
        now = datetime.now()
        
        # 시간대별 키 생성
        # 형식: "stats:hourly:{metric_name}:{hour}"
        hourly_key = f"{self.STATS_PREFIX}hourly:{metric_name}:{now.hour}"
        
        # 해당 시간대의 카운트 조회
        count = self.client.get(hourly_key)
        
        return {
            'hour': now.hour,  # 0-23 사이의 정수
            'count': int(count) if count else 0
        }


# ============================================
# 4. RAG 질의응답 캐싱
# ============================================
class RAGCacheService(RedisService):
    """
    RAG 질의응답 결과 캐싱 서비스
    
    LLM을 사용한 RAG(Retrieval-Augmented Generation) 질의응답의 결과를
    Redis에 캐싱하여 동일한 질문에 대한 반복적인 LLM 호출을 방지합니다.
    
    주요 기능:
    - 쿼리 텍스트를 해시화하여 캐시 키 생성
    - 캐시된 응답 조회
    - 새로운 응답 캐싱
    - 특정 쿼리 캐시 무효화
    
    캐시 전략:
    - 기본 TTL: 24시간 (86400초)
    - 쿼리 정규화: 소문자 변환 및 공백 제거로 유사한 질문도 동일하게 처리
    
    사용 예시:
        cache_service = RAGCacheService()
        
        # 캐시 확인
        cached = cache_service.get_cached_response("오늘 날씨는?")
        if cached:
            return cached
        
        # LLM 처리 후 캐싱
        response = llm.query("오늘 날씨는?")
        cache_service.cache_response("오늘 날씨는?", response)
    """
    
    def __init__(self):
        """
        RAG 캐싱 서비스 초기화
        
        RedisService를 상속받아 Redis 연결을 설정하고,
        캐시 키 접두사와 기본 TTL을 설정합니다.
        """
        super().__init__()  # Redis 연결 초기화
        self.CACHE_PREFIX = "rag:query:"  # Redis 키 접두사
        # TTL 설정: 24시간 (초 단위로 미리 계산)
        self.CACHE_TTL = 24 * 3600  # 86400초 (24시간)
    
    def get_cache_key(self, query: str) -> str:
        """
        쿼리 텍스트를 기반으로 캐시 키 생성
        
        동일한 의미의 질문을 동일한 키로 매핑하기 위해:
        1. 소문자로 변환
        2. 앞뒤 공백 제거
        3. MD5 해시화하여 고정 길이 키 생성
        
        Args:
            query: 사용자 질의 텍스트
            
        Returns:
            Redis 캐시 키 (예: "rag:query:a1b2c3d4e5f6...")
            
        예시:
            "오늘 날씨는?" -> "rag:query:abc123..."
            "오늘  날씨는?  " -> "rag:query:abc123..." (동일한 키)
        """
        # 쿼리 정규화: 소문자 변환 및 공백 제거
        # 이렇게 하면 "오늘 날씨는?"과 "오늘  날씨는?"이 동일한 키가 됩니다
        normalized = query.lower().strip()
        
        # MD5 해시를 사용하여 고정 길이 키 생성
        # 해시를 사용하는 이유:
        # 1. 키 길이 제한 해결 (Redis 키는 최대 512MB이지만 실용적으로는 짧게)
        # 2. 특수문자 문제 해결
        # 3. 일관된 키 형식 보장
        query_hash = hashlib.md5(normalized.encode()).hexdigest()
        
        return f"{self.CACHE_PREFIX}{query_hash}"
    
    def get_cached_response(self, query: str) -> Optional[Dict]:
        """
        캐시된 답변 조회
        
        Redis에서 해당 쿼리의 캐시된 응답을 조회합니다.
        캐시가 없거나 만료된 경우 None을 반환합니다.
        
        Args:
            query: 사용자 질의 텍스트
            
        Returns:
            캐시된 응답 딕셔너리 또는 None
            
        예시:
            cached = cache_service.get_cached_response("오늘 날씨는?")
            if cached:
                return cached['answer']  # 캐시된 답변 사용
        """
        # 쿼리를 기반으로 캐시 키 생성
        cache_key = self.get_cache_key(query)
        
        # Redis에서 값 조회
        # GET 명령어는 키가 없거나 만료된 경우 None을 반환
        cached = self.client.get(cache_key)
        
        if cached:
            # JSON 문자열을 파이썬 딕셔너리로 변환
            # ensure_ascii=False 옵션으로 한글 등 유니코드 문자 보존
            return json.loads(cached)
        
        # 캐시가 없는 경우
        return None
    
    def cache_response(self, query: str, response: Dict, ttl: Optional[int] = None):
        """
        RAG 응답 캐싱
        
        LLM으로 생성한 응답을 Redis에 저장합니다.
        SETEX 명령어를 사용하여 키와 함께 TTL(Time To Live)을 설정합니다.
        
        Args:
            query: 사용자 질의 텍스트
            response: LLM 응답 딕셔너리 (예: {'answer': '...', 'sources': [...]})
            ttl: 캐시 유지 시간(초). None이면 기본값(24시간) 사용
            
        동작 원리:
            SETEX key seconds value
            - key: 캐시 키
            - seconds: TTL (초 단위)
            - value: JSON 문자열로 변환된 응답
            
        예시:
            response = {
                'answer': '오늘 날씨는 맑습니다.',
                'sources': ['기상청 데이터']
            }
            cache_service.cache_response("오늘 날씨는?", response)
        """
        # 캐시 키 생성
        cache_key = self.get_cache_key(query)
        
        # TTL 설정 (지정하지 않으면 기본값 사용)
        ttl = ttl or self.CACHE_TTL
        
        # Redis에 저장
        # SETEX: SET with EXpiration (만료 시간과 함께 저장)
        # json.dumps: 딕셔너리를 JSON 문자열로 변환
        # ensure_ascii=False: 한글 등 유니코드 문자를 그대로 유지
        self.client.setex(
            cache_key,
            ttl,
            json.dumps(response, ensure_ascii=False)
        )
    
    def invalidate_cache(self, query: str):
        """
        특정 쿼리 캐시 무효화
        
        특정 질문의 캐시를 강제로 삭제합니다.
        데이터가 업데이트되어 캐시를 갱신해야 할 때 사용합니다.
        
        Args:
            query: 삭제할 캐시의 질의 텍스트
            
        사용 시나리오:
            - 새로운 데이터가 추가되어 이전 답변이 부정확해진 경우
            - 관리자가 특정 질문의 캐시를 수동으로 갱신하고 싶은 경우
            
        예시:
            # 데이터 업데이트 후
            cache_service.invalidate_cache("오늘 날씨는?")
            # 다음 요청부터는 새로운 데이터로 답변 생성
        """
        # 캐시 키 생성
        cache_key = self.get_cache_key(query)
        
        # Redis에서 키 삭제
        # DELETE 명령어로 해당 키를 즉시 제거
        self.client.delete(cache_key)


# ============================================
# 5. API Rate Limiting (외부 API 호출 제한)
# ============================================
class RateLimitService(RedisService):
    """
    API Rate Limiting 서비스
    
    외부 API(Twitter, 뉴스 API 등) 호출 시
    Rate Limit을 관리하여 API 할당량을 초과하지 않도록 합니다.
    
    동작 원리:
    - 각 API 키별로 요청 횟수를 카운트
    - 시간 윈도우(예: 1시간) 내 최대 요청 수 제한
    - TTL을 사용하여 시간 윈도우 자동 관리
    
    주요 기능:
    - Rate Limit 체크 (요청 허용 여부 확인)
    - Rate Limit 상태 조회
    
    사용 예시:
        rate_limit = RateLimitService()
        
        # Rate Limit 체크
        check = rate_limit.check_rate_limit(
            identifier='twitter_api_key_123',
            max_requests=100,  # 시간당 최대 100회
            window_seconds=3600  # 1시간 윈도우
        )
        
        if not check['allowed']:
            return {'error': 'Rate limit exceeded'}
        
        # API 호출 진행
        result = twitter_api.get_tweets()
    """
    
    def __init__(self):
        """
        Rate Limiting 서비스 초기화
        
        Redis 연결을 설정하고, 키 접두사와 기본값을 설정합니다.
        """
        super().__init__()  # Redis 연결 초기화
        self.RATE_LIMIT_PREFIX = "ratelimit:"  # Redis 키 접두사
        # 기본 Rate Limit 설정
        # 필요시 check_rate_limit() 호출 시 다른 값으로 오버라이드 가능
        self.DEFAULT_MAX_REQUESTS = 100  # 기본 최대 요청 수 (시간당)
        self.DEFAULT_WINDOW_SECONDS = 3600  # 기본 시간 윈도우 (1시간, 초 단위)
    
    def check_rate_limit(
        self,
        identifier: str,  # API 키, IP, 사용자 ID 등
        max_requests: Optional[int] = None,  # None이면 기본값 사용
        window_seconds: Optional[int] = None  # None이면 기본값 사용
    ) -> Dict[str, Any]:
        """
        Rate Limit 체크
        
        현재 요청이 허용되는지 확인하고, 허용되면 카운터를 증가시킵니다.
        
        Args:
            identifier: 식별자 (API 키, IP 주소, 사용자 ID 등)
            max_requests: 시간 윈도우 내 최대 요청 수 
                         (None이면 기본값 사용: self.DEFAULT_MAX_REQUESTS)
            window_seconds: 시간 윈도우 크기 (초 단위)
                           (None이면 기본값 사용: self.DEFAULT_WINDOW_SECONDS)
            
        Returns:
            {
                'allowed': bool,        # 요청 허용 여부
                'remaining': int,      # 남은 요청 수
                'reset_at': datetime,  # 리셋 시간
                'limit': int           # 최대 요청 수
            }
            
        동작 과정:
            1. 현재 요청 수 조회
            2. 최대치 초과 여부 확인
            3. 초과 시: 허용하지 않음, 리셋 시간 반환
            4. 미만 시: 카운터 증가, 허용함
            
        Redis 키 형식:
            "ratelimit:twitter_api_key_123"
            
        TTL 관리:
            - 첫 요청 시 SETEX로 TTL 설정
            - 이후 요청은 INCR로 카운터만 증가
            - TTL이 지나면 자동으로 키 삭제 (리셋)
            
        예시:
            # 기본값 사용 (시간당 100회)
            check = rate_limit.check_rate_limit('api_key_123')
            
            # 커스텀 값 사용
            check = rate_limit.check_rate_limit(
                'api_key_123',
                max_requests=50,  # 시간당 50회
                window_seconds=3600  # 1시간
            )
            
            if check['allowed']:
                print(f"요청 허용, 남은 횟수: {check['remaining']}")
            else:
                print(f"요청 거부, 리셋 시간: {check['reset_at']}")
        """
        # 기본값 설정 (파라미터가 None이면 기본값 사용)
        max_requests = max_requests or self.DEFAULT_MAX_REQUESTS
        window_seconds = window_seconds or self.DEFAULT_WINDOW_SECONDS
        
        # Redis 키 생성
        # identifier는 문자열(예: 'api_key_123', '192.168.1.1')이고
        # 이것을 키 이름으로 사용합니다
        key = f"{self.RATE_LIMIT_PREFIX}{identifier}"
        
        # 현재 요청 수 조회
        # GET 명령어로 Redis에 저장된 카운터 값 가져오기
        # decode_responses=True로 인해 문자열로 반환됨 (예: "1", "2", "3")
        # 저장된 값은 숫자 카운터이므로 int()로 변환 필요
        current = self.client.get(key)
        # current가 None이면 키가 없음(아직 요청 없음) → 0
        # current가 문자열이면 int()로 변환 (예: "1" → 1)
        current_count = int(current) if current else 0
        
        # 최대치 초과 확인
        if current_count >= max_requests:
            # Rate Limit 초과
            # TTL을 조회하여 리셋 시간 계산
            ttl = self.client.ttl(key)  # 남은 시간(초) 반환
            
            # 현재 시간 + 남은 시간 = 리셋 시간
            reset_at = datetime.now() + timedelta(seconds=ttl)
            
            return {
                'allowed': False,
                'remaining': 0,
                'reset_at': reset_at,
                'limit': max_requests
            }
        
        # 요청 허용
        # 카운터 증가
        if current_count == 0:
            # 첫 요청: SETEX로 카운터와 TTL 함께 설정
            # window_seconds 후 자동으로 키가 삭제되어 리셋됨
            self.client.setex(key, window_seconds, 1)
        else:
            # 이후 요청: INCR로 카운터만 증가
            # TTL은 이미 설정되어 있으므로 유지됨
            self.client.incr(key)
        
        # 남은 요청 수 계산
        remaining = max_requests - (current_count + 1)
        
        # 리셋 시간 계산 (현재 시간 + 윈도우 크기)
        reset_at = datetime.now() + timedelta(seconds=window_seconds)
        
        return {
            'allowed': True,
            'remaining': remaining,
            'reset_at': reset_at,
            'limit': max_requests
        }
    
    def get_rate_limit_status(self, identifier: str) -> Dict:
        """
        Rate Limit 상태 조회
        
        현재 Rate Limit 상태를 조회합니다. (카운터 증가 없음)
        
        Args:
            identifier: 식별자
            
        Returns:
            {
                'current': int,           # 현재 요청 수
                'reset_in_seconds': int  # 리셋까지 남은 시간(초)
            }
            
        사용 목적:
            - 모니터링
            - 사용자에게 남은 요청 수 표시
            - 디버깅
            
        예시:
            status = rate_limit.get_rate_limit_status('api_key_123')
            print(f"현재 요청 수: {status['current']}")
            print(f"리셋까지: {status['reset_in_seconds']}초")
        """
        # Redis 키 생성
        key = f"{self.RATE_LIMIT_PREFIX}{identifier}"
        
        # 현재 카운터 값 조회
        current = self.client.get(key)
        
        # TTL 조회 (리셋까지 남은 시간)
        ttl = self.client.ttl(key)
        
        return {
            'current': int(current) if current else 0,
            'reset_in_seconds': ttl if ttl > 0 else 0
            # ttl이 -1이면 TTL이 설정되지 않음
            # ttl이 -2이면 키가 존재하지 않음
            # 둘 다 0으로 처리
        }


# ============================================
# 6. 분석 결과 최신 캐시
# ============================================
class AnalysisCacheService(RedisService):
    """
    분석 결과 최신 캐시 서비스
    
    분석 결과를 Redis에 저장하여 대시보드에서 빠르게 조회할 수 있게 합니다.
    DB에는 이력/요약을 저장하고, Redis에는 최신 결과 전체를 저장하는 하이브리드 구조에 사용됩니다.
    """
    
    def __init__(self):
        """
        분석 캐시 서비스 초기화
        
        settings.py에서 ANALYSIS_CACHE_TTL_SECONDS 값을 읽어옵니다.
        기본 TTL은 6시간(21600초)입니다.
        """
        super().__init__()
        self.ANALYSIS_PREFIX = "analysis:latest:"
        self.CACHE_TTL = int(
            getattr(settings, 'ANALYSIS_CACHE_TTL_SECONDS', 6 * 3600)
        )
    
    def get_cache_key(
        self,
        analysis_type: str,
        platform: Optional[str] = None,
        days: Optional[int] = None,
        parameters: Optional[Dict[str, Any]] = None
    ) -> str:
        """
        분석 파라미터 기반 캐시 키 생성
        """
        params = {
            'analysis_type': analysis_type,
            'platform': platform,
            'days': days
        }
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
        parameters: Optional[Dict[str, Any]] = None
    ) -> Optional[Dict[str, Any]]:
        """
        최신 분석 결과 조회
        """
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
        ttl: Optional[int] = None
    ):
        """
        최신 분석 결과 캐싱
        """
        cache_key = self.get_cache_key(analysis_type, platform, days, parameters)
        ttl = ttl or self.CACHE_TTL
        self.client.setex(
            cache_key,
            ttl,
            json.dumps(result, ensure_ascii=False, default=str)
        )
