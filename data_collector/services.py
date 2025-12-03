"""
데이터 수집 서비스 모듈

이 모듈은 RSS 피드 수집을 위한 서비스 클래스를 제공합니다.
클래스 기반 구조로 여러 뉴스 소스를 일관되게 처리할 수 있습니다.
"""
import logging
import feedparser
from datetime import datetime
from typing import List, Dict, Optional, Tuple
from urllib.parse import urlparse
from django.utils import timezone
from common.redis_services import (
    DuplicatePreventionService,
    RateLimitService,
    RealtimeStatsService
)
from .models import NewsSource, NewsArticle, DataCollectionJob

# 로거 설정
logger = logging.getLogger(__name__)


class RSSCollectorService:
    """
    RSS 피드 수집 서비스 클래스
    
    RSS 피드를 파싱하고 뉴스 기사를 수집하여 데이터베이스에 저장하는 서비스입니다.
    Redis를 활용한 중복 방지, Rate Limiting, 통계 집계 등의 기능을 제공합니다.
    
    주요 기능:
    1. RSS 피드 파싱
    2. 중복 수집 방지 (Redis)
    3. Rate Limiting
    4. 실시간 통계 집계
    5. 수집 작업 로그 기록
    
    사용 예시:
        collector = RSSCollectorService()
        
        # 특정 소스에서 수집
        result = collector.collect(source_id=1)
        
        # 또는 소스 객체 직접 전달
        source = NewsSource.objects.get(name='경향신문')
        result = collector.collect_from_source(source)
    """
    
    def __init__(self):
        """
        RSS 수집 서비스 초기화
        
        Redis 서비스들을 초기화하고 로거를 설정합니다.
        """
        # Redis 서비스 초기화
        # 중복 방지, Rate Limiting, 통계 집계를 위한 서비스들
        self.duplicate_check = DuplicatePreventionService()
        self.rate_limit = RateLimitService()
        self.stats = RealtimeStatsService()
        
        # 로거 설정
        self.logger = logging.getLogger(__name__)
    
    def parse_feed(self, rss_url: str) -> List[Dict]:
        """
        RSS 피드를 파싱하여 기사 목록을 반환하는 메서드
        
        feedparser 라이브러리를 사용하여 RSS/Atom 피드를 파싱하고,
        각 기사 항목을 딕셔너리 형태로 변환합니다.
        
        Args:
            rss_url: RSS 피드 URL (예: 'https://www.khan.co.kr/rss/rssdata/total_news.xml')
            
        Returns:
            기사 정보 딕셔너리 리스트. 각 딕셔너리는 다음 키를 포함:
            - title: 기사 제목
            - link: 기사 URL
            - description: 기사 설명/요약
            - published: 발행 시간 (datetime 객체)
            - author: 작성자
            - category: 카테고리
            
        예외 처리:
            - 네트워크 오류, 파싱 오류 등이 발생하면 빈 리스트를 반환하고 로그를 기록합니다.
            
        사용 예시:
            collector = RSSCollectorService()
            articles = collector.parse_feed('https://www.khan.co.kr/rss/rssdata/total_news.xml')
            for article in articles:
                print(article['title'])
        """
        try:
            # feedparser를 사용하여 RSS 피드 파싱
            # feedparser.parse()는 URL을 직접 받아서 HTTP 요청을 수행하고 파싱합니다.
            feed = feedparser.parse(rss_url)
            
            # 파싱 결과 확인
            # feed.bozo는 파싱 오류가 발생했는지 여부를 나타냅니다.
            if feed.bozo and feed.bozo_exception:
                self.logger.warning(
                    f"RSS 피드 파싱 경고: {rss_url} - {feed.bozo_exception}"
                )
            
            # 기사 목록 추출
            articles = []
            
            # feed.entries는 RSS 피드의 각 <item> 또는 Atom 피드의 각 <entry>에 해당합니다.
            for entry in feed.entries:
                try:
                    # 발행 시간 파싱
                    # feedparser는 다양한 날짜 형식을 자동으로 파싱합니다.
                    published_time = None
                    if hasattr(entry, 'published_parsed') and entry.published_parsed:
                        # published_parsed는 time.struct_time 객체입니다.
                        # 이를 datetime 객체로 변환합니다.
                        from time import mktime
                        published_time = datetime.fromtimestamp(
                            mktime(entry.published_parsed)
                        )
                    elif hasattr(entry, 'updated_parsed') and entry.updated_parsed:
                        # published가 없으면 updated를 사용합니다.
                        from time import mktime
                        published_time = datetime.fromtimestamp(
                            mktime(entry.updated_parsed)
                        )
                    
                    # 기사 정보 딕셔너리 생성
                    article = {
                        'title': entry.get('title', '').strip(),  # 제목
                        'link': entry.get('link', '').strip(),    # URL
                        'description': entry.get('description', '').strip(),  # 설명
                        'published': published_time,  # 발행 시간 (datetime 객체)
                        'author': entry.get('author', '').strip() if hasattr(entry, 'author') else '',  # 작성자
                        'category': entry.get('category', '').strip() if hasattr(entry, 'category') else '',  # 카테고리
                    }
                    
                    # 필수 필드 검증 (제목과 URL은 반드시 있어야 함)
                    if article['title'] and article['link']:
                        articles.append(article)
                    else:
                        self.logger.warning(
                            f"필수 필드가 없는 기사 건너뜀: {article}"
                        )
                        
                except Exception as e:
                    # 개별 기사 파싱 오류는 로그만 남기고 계속 진행
                    self.logger.error(
                        f"기사 파싱 오류 (URL: {rss_url}): {str(e)}",
                        exc_info=True
                    )
                    continue
            
            self.logger.info(
                f"RSS 피드 파싱 완료: {rss_url} - {len(articles)}개 기사 발견"
            )
            return articles
            
        except Exception as e:
            # 전체 파싱 실패 시 로그 기록
            self.logger.error(
                f"RSS 피드 파싱 실패: {rss_url} - {str(e)}",
                exc_info=True
            )
            return []
    
    def collect_from_source(self, source: NewsSource) -> Dict:
        """
        특정 뉴스 소스에서 기사를 수집하는 메서드
        
        NewsSource 객체를 받아서 해당 소스의 RSS 피드를 수집합니다.
        중복 방지, Rate Limiting, 통계 집계 등의 기능을 모두 포함합니다.
        
        Args:
            source: NewsSource 모델 인스턴스
            
        Returns:
            수집 결과 딕셔너리:
            {
                'status': 'completed' | 'rate_limited' | 'failed',
                'source': 소스 이름,
                'items_collected': 수집된 기사 수,
                'items_skipped': 건너뛴 기사 수,
                'items_error': 오류 발생 기사 수,
                'total_items': 전체 기사 수
            }
            
        사용 예시:
            source = NewsSource.objects.get(name='경향신문')
            collector = RSSCollectorService()
            result = collector.collect_from_source(source)
            print(f"수집 완료: {result['items_collected']}개")
        """
        # 수집 작업 로그 생성
        job = None
        try:
            # 수집 작업 로그 생성
            job = DataCollectionJob.objects.create(
                source=source,
                status='running',
                started_at=timezone.now()
            )
            
            # Rate Limit 체크
            # RSS 피드는 일반적으로 Rate Limit이 없지만,
            # 과도한 요청을 방지하기 위해 체크합니다.
            limit_check = self.rate_limit.check_rate_limit(
                identifier=f"rss_{source.id}",
                max_requests=10,  # 시간당 최대 10회 요청
                window_seconds=3600  # 1시간 윈도우
            )
            
            if not limit_check['allowed']:
                # Rate limit 초과 시 작업 실패 처리
                error_msg = (
                    f"Rate limit 초과. "
                    f"리셋 시간: {limit_check['reset_at']}"
                )
                self.logger.warning(error_msg)
                
                if job:
                    job.status = 'failed'
                    job.error_message = error_msg
                    job.completed_at = timezone.now()
                    job.save()
                
                return {
                    'status': 'rate_limited',
                    'message': error_msg,
                    'reset_at': limit_check['reset_at'].isoformat(),
                    'source': str(source),
                    'items_collected': 0
                }
            
            # RSS 피드 파싱
            self.logger.info(f"RSS 피드 수집 시작: {str(source)} ({source.url})")
            articles = self.parse_feed(source.url)
            
            if not articles:
                # 기사가 없는 경우
                self.logger.warning(f"수집된 기사가 없습니다: {str(source)}")
                
                if job:
                    job.status = 'completed'
                    job.items_collected = 0
                    job.completed_at = timezone.now()
                    job.save()
                
                # 소스의 마지막 수집 시간 업데이트
                source.last_collected_at = timezone.now()
                source.save(update_fields=['last_collected_at'])
                
                return {
                    'status': 'completed',
                    'message': '수집된 기사가 없습니다',
                    'source': str(source),
                    'items_collected': 0
                }
            
            # 수집된 기사 개수 추적
            collected_count = 0
            skipped_count = 0
            error_count = 0
            
            # 각 기사 처리
            for article in articles:
                article_url = article.get('link', '').strip()
                
                # URL이 없으면 건너뜀
                if not article_url:
                    self.logger.warning("URL이 없는 기사 건너뜀")
                    skipped_count += 1
                    continue
                
                try:
                    # 중복 체크 (Redis)
                    # 이미 수집한 기사인지 확인합니다.
                    # Redis 키 형식: "collected:news:{article_url}"
                    if self.duplicate_check.is_already_collected('news', article_url):
                        self.logger.debug(f"이미 수집한 기사 건너뜀: {article_url}")
                        skipped_count += 1
                        continue
                    
                    # 데이터베이스에 기사 저장
                    # get_or_create를 사용하여 중복 저장을 방지합니다.
                    # (Redis 체크와 DB 체크를 모두 수행하여 이중 안전장치)
                    news_article, created = NewsArticle.objects.get_or_create(
                        url=article_url,
                        defaults={
                            'source': source,
                            'title': article.get('title', ''),
                            'description': article.get('description', ''),
                            'author': article.get('author', '')[:200] if article.get('author') else '',
                            'category': article.get('category', '')[:100] if article.get('category') else '',
                            'published_at': article.get('published'),
                        }
                    )
                    
                    if created:
                        # 새로 생성된 기사인 경우
                        collected_count += 1
                        
                        # Redis에 수집 완료 표시
                        # 다음 수집 시 중복 체크를 위해 Redis에 기록합니다.
                        self.duplicate_check.mark_as_collected('news', article_url)
                        
                        # 실시간 통계 업데이트
                        # 수집된 기사 수를 카운터로 증가시킵니다.
                        self.stats.increment_counter('articles_collected')
                        # 시간대별 카운터도 증가 (시간대별 통계 집계)
                        self.stats.increment_hourly_counter('articles_collected')
                        self.stats.record_timestamp('article_collected')
                        
                        self.logger.debug(
                            f"기사 수집 완료: {news_article.title[:50]}..."
                        )
                    else:
                        # 이미 존재하는 기사 (DB에만 있고 Redis에는 없었던 경우)
                        # Redis에 표시를 남겨서 다음 수집 시 건너뛰도록 합니다.
                        self.duplicate_check.mark_as_collected('news', article_url)
                        skipped_count += 1
                        
                except Exception as e:
                    # 개별 기사 저장 오류
                    error_count += 1
                    self.logger.error(
                        f"기사 저장 오류 (URL: {article_url}): {str(e)}",
                        exc_info=True
                    )
                    continue
            
            # 소스의 마지막 수집 시간 업데이트
            source.last_collected_at = timezone.now()
            source.save(update_fields=['last_collected_at'])
            
            # 수집 작업 로그 업데이트
            if job:
                job.status = 'completed'
                job.items_collected = collected_count
                job.completed_at = timezone.now()
                job.save()
            
            # 결과 로그
            self.logger.info(
                f"RSS 수집 완료: {str(source)} - "
                f"수집: {collected_count}개, "
                f"건너뜀: {skipped_count}개, "
                f"오류: {error_count}개"
            )
            
            return {
                'status': 'completed',
                'source': source.name,
                'items_collected': collected_count,
                'items_skipped': skipped_count,
                'items_error': error_count,
                'total_items': len(articles)
            }
            
        except Exception as e:
            # 전체 작업 실패 처리
            error_msg = f"RSS 수집 작업 실패: {str(e)}"
            self.logger.error(error_msg, exc_info=True)
            
            # 수집 작업 로그 업데이트
            if job:
                job.status = 'failed'
                job.error_message = error_msg
                job.completed_at = timezone.now()
                job.save()
            
            return {
                'status': 'failed',
                'message': error_msg,
                'source': str(source) if source else 'Unknown',
                'items_collected': 0
            }
    
    def collect(self, source_id: Optional[int] = None, source_name: Optional[str] = None) -> Dict:
        """
        뉴스 소스 ID 또는 이름으로 기사를 수집하는 메서드
        
        source_id 또는 source_name으로 NewsSource를 조회한 후 수집을 진행합니다.
        둘 다 None이면 활성화된 모든 RSS 소스를 수집합니다.
        
        Args:
            source_id: NewsSource 모델의 ID (선택)
            source_name: NewsSource의 이름 (선택, 예: '경향신문')
            
        Returns:
            수집 결과 딕셔너리 또는 결과 리스트
            
        사용 예시:
            collector = RSSCollectorService()
            
            # ID로 수집
            result = collector.collect(source_id=1)
            
            # 이름으로 수집
            result = collector.collect(source_name='경향신문')
            
            # 모든 활성화된 소스 수집
            results = collector.collect()
        """
        if source_id:
            # source_id로 소스 조회
            try:
                source = NewsSource.objects.get(id=source_id, is_active=True)
                return self.collect_from_source(source)
            except NewsSource.DoesNotExist:
                error_msg = f"활성화된 뉴스 소스를 찾을 수 없습니다: ID={source_id}"
                self.logger.error(error_msg)
                return {
                    'status': 'failed',
                    'message': error_msg
                }
        
        elif source_name:
            # source_name으로 소스 조회
            try:
                # source_name으로 소스 조회 (publisher 또는 publisher - category 형식)
                if ' - ' in source_name:
                    parts = source_name.split(' - ', 1)
                    source = NewsSource.objects.get(
                        publisher=parts[0],
                        category=parts[1] if len(parts) > 1 else None,
                        is_active=True
                    )
                else:
                    # publisher만 있는 경우 첫 번째 활성 소스 반환
                    source = NewsSource.objects.filter(
                        publisher=source_name,
                        is_active=True
                    ).first()
                    if not source:
                        raise NewsSource.DoesNotExist
                return self.collect_from_source(source)
            except NewsSource.DoesNotExist:
                error_msg = f"활성화된 뉴스 소스를 찾을 수 없습니다: 이름={source_name}"
                self.logger.error(error_msg)
                return {
                    'status': 'failed',
                    'message': error_msg
                }
        
        else:
            # 모든 활성화된 RSS 소스 수집
            sources = NewsSource.objects.filter(
                is_active=True,
                source_type='rss'
            )
            
            results = []
            for source in sources:
                result = self.collect_from_source(source)
                results.append(result)
            
            return {
                'status': 'completed',
                'sources_count': len(results),
                'results': results
            }

    def create_source_from_rss(
        self,
        rss_url: str,
        name: Optional[str] = None,
        is_active: bool = True,
        collection_interval: int = 60
    ) -> Tuple[Optional[NewsSource], str, Dict]:
        """
        RSS URL로부터 NewsSource를 생성하는 메서드

        RSS 피드를 파싱하여 소스 정보를 추출하고 NewsSource를 생성합니다.
        이미 존재하는 URL인 경우 기존 소스를 반환합니다.

        Args:
            rss_url: RSS 피드 URL
            name: 소스 이름 (선택, 없으면 자동 추출)
            is_active: 활성화 여부 (기본값: True)
            collection_interval: 수집 주기(분) (기본값: 60)

        Returns:
            (source, status, result_dict) 튜플:
            - source: 생성된 또는 기존 NewsSource 객체 (실패 시 None)
            - status: 'created' | 'exists' | 'error'
            - result_dict: 상세 결과 딕셔너리

        사용 예시:
            collector = RSSCollectorService()
            source, status, result = collector.create_source_from_rss(
                'https://www.khan.co.kr/rss/rssdata/total_news.xml'
            )
            if status == 'created':
                print(f"생성 완료: {str(source)}")
        """
        try:
            # RSS 피드 파싱하여 정보 추출
            feed = feedparser.parse(rss_url)

            if feed.bozo and feed.bozo_exception:
                error_msg = (
                    f'유효하지 않은 RSS 피드입니다: '
                    f'{str(feed.bozo_exception)}'
                )
                self.logger.error(error_msg)
                return None, 'error', {'message': error_msg}

            # 소스 이름 추출 (피드 제목 또는 도메인명)
            parsed_url = urlparse(rss_url)
            source_name = (
                name or
                feed.feed.get('title', '').strip() or
                parsed_url.netloc.replace('www.', '')
            )

            if not source_name:
                domain = parsed_url.netloc
                source_name = f"RSS Source {domain}"

            # 이미 존재하는 소스인지 확인
            if NewsSource.objects.filter(url=rss_url).exists():
                existing_source = NewsSource.objects.get(url=rss_url)
                self.logger.info(
                    f"이미 등록된 RSS 소스: {str(existing_source)} "
                    f"({rss_url})"
                )
                return existing_source, 'exists', {
                    'message': '이미 등록된 RSS 소스입니다.'
                }

            # NewsSource 생성
            # source_name이 "publisher - category" 형식이면 분리, 아니면 publisher만
            if ' - ' in source_name:
                parts = source_name.split(' - ', 1)
                publisher = parts[0]
                category = parts[1] if len(parts) > 1 else None
            else:
                publisher = source_name
                category = None
            
            source = NewsSource.objects.create(
                publisher=publisher,
                category=category,
                url=rss_url,
                source_type='rss',
                is_active=is_active,
                collection_interval=collection_interval
            )

            self.logger.info(
                f"RSS 소스 자동 생성: {source_name} ({rss_url})"
            )

            return source, 'created', {
                'message': 'RSS 소스가 성공적으로 생성되었습니다.'
            }

        except Exception as e:
            error_msg = f'RSS 소스 생성 실패: {str(e)}'
            self.logger.error(error_msg, exc_info=True)
            return None, 'error', {'message': error_msg}

