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
from .models import NewsSource, NewsArticle, DataCollectionJob, SocialMediaSource, SocialMediaPost

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
                'source': str(source),
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


class NewsSourceCSVService:
    """
    CSV 파일에서 NewsSource를 일괄 생성하는 서비스 클래스
    
    CSV 파일을 읽어서 NewsSource 객체를 생성하거나 업데이트합니다.
    중복 체크, 오류 처리, 상세한 결과 반환 등의 기능을 제공합니다.
    
    사용 예시:
        service = NewsSourceCSVService()
        results = service.load_sources_from_csv('NewsSource_RSS.csv')
        print(f"생성: {results['created']}개, 업데이트: {results['updated']}개")
    """
    
    def __init__(self):
        """서비스 초기화"""
        self.logger = logging.getLogger(__name__)
    
    def load_sources_from_csv(self, csv_file_path: str = None) -> dict:
        """
        CSV 파일에서 NewsSource를 생성하는 메서드
        
        Args:
            csv_file_path: CSV 파일 경로 (None이면 기본 경로 사용)
        
        Returns:
            결과 딕셔너리:
            {
                'created': 생성된 소스 수,
                'updated': 업데이트된 소스 수,
                'skipped': 건너뛴 행 수,
                'errors': 오류 발생 행 수,
                'sources': 생성/업데이트된 소스 정보 리스트,
                'error_details': 오류 상세 정보 리스트
            }
        """
        import csv
        import os
        from django.conf import settings
        from django.db import transaction
        from .models import NewsSource
        from .serializers import NewsSourceSerializer
        
        results = {
            'created': 0,
            'updated': 0,
            'skipped': 0,
            'errors': 0,
            'sources': [],
            'error_details': []
        }

        try:
            # CSV 파일 경로 결정
            if csv_file_path:
                csv_path = csv_file_path
            else:
                # 기본 경로: 프로젝트 루트의 NewsSource_RSS.csv
                csv_path = os.path.join(
                    settings.BASE_DIR,
                    'NewsSource_RSS.csv'
                )

            # CSV 파일 경로 확인
            if not os.path.exists(csv_path):
                self.logger.error(f"CSV 파일을 찾을 수 없습니다: {csv_path}")
                results['errors'] = 1
                results['error_details'].append(f"CSV 파일을 찾을 수 없습니다: {csv_path}")
                return results

            # CSV 파일 읽기
            with open(csv_path, 'r', encoding='utf-8') as f:
                reader = csv.DictReader(f)

                for row in reader:
                    try:
                        publisher = row.get('publisher', '').strip()
                        category = row.get('title', '').strip()  # CSV의 title이 카테고리
                        url = row.get('url', '').strip()

                        # 필수 필드 검증
                        if not publisher or not url:
                            self.logger.warning(
                                f"필수 필드가 없는 행 건너뜀: {row}"
                            )
                            results['skipped'] += 1
                            continue

                        # 1. URL로 먼저 확인 (가장 정확)
                        existing_source = (
                            NewsSource.objects.filter(url=url).first()
                        )

                        # 2. URL이 없으면 publisher + category로 확인
                        if not existing_source:
                            existing_source = (
                                NewsSource.objects.filter(
                                    publisher=publisher,
                                    category=category
                                ).first()
                            )

                        if existing_source:
                            # 기존 소스 업데이트
                            updated_fields = []
                            
                            # URL이 다르면 업데이트
                            if existing_source.url != url:
                                existing_source.url = url
                                updated_fields.append('url')
                            
                            # publisher가 다르면 업데이트
                            if existing_source.publisher != publisher:
                                existing_source.publisher = publisher
                                updated_fields.append('publisher')
                            
                            # category가 다르면 업데이트
                            if existing_source.category != category:
                                existing_source.category = category
                                updated_fields.append('category')
                            
                            if updated_fields:
                                existing_source.save(update_fields=updated_fields)
                                self.logger.info(
                                    f"소스 업데이트: {publisher} - {category} ({url}) - "
                                    f"변경된 필드: {', '.join(updated_fields)}"
                                )
                            
                            results['updated'] += 1
                            serializer = NewsSourceSerializer(
                                existing_source
                            )
                            results['sources'].append(serializer.data)
                        else:
                            # 새 소스 생성
                            try:
                                with transaction.atomic():
                                    source = NewsSource.objects.create(
                                        publisher=publisher,
                                        category=category if category else None,
                                        url=url,
                                        source_type='rss',
                                        is_active=True,
                                        collection_interval=60
                                    )
                                    results['created'] += 1
                                    serializer = NewsSourceSerializer(source)
                                    results['sources'].append(serializer.data)
                                    self.logger.info(
                                        f"새 소스 생성: {publisher} - {category} ({url})"
                                    )
                            except Exception as create_error:
                                # 중복 오류인 경우, 기존 것을 찾아서 업데이트
                                if 'unique' in str(create_error).lower() or 'duplicate' in str(create_error).lower():
                                    existing_by_pub_cat = (
                                        NewsSource.objects.filter(
                                            publisher=publisher,
                                            category=category
                                        ).first()
                                    )
                                    if existing_by_pub_cat:
                                        existing_by_pub_cat.url = url
                                        existing_by_pub_cat.save(update_fields=['url'])
                                        results['updated'] += 1
                                        self.logger.info(
                                            f"중복으로 인한 업데이트: {publisher} - {category} "
                                            f"(URL 변경: {url})"
                                        )
                                        continue
                                # 다른 오류면 다시 raise
                                raise

                    except Exception as e:
                        error_msg = str(e)
                        self.logger.error(
                            f"소스 생성 오류 (행: {row}): {error_msg}",
                            exc_info=True
                        )
                        results['errors'] += 1
                        # 오류 상세 정보 저장
                        results['error_details'].append({
                            'row': row,
                            'error': error_msg,
                            'publisher': row.get('publisher', ''),
                            'title': row.get('title', ''),
                            'url': row.get('url', '')
                        })
                        continue

            self.logger.info(
                f"CSV 파일 로드 완료: 생성={results['created']}, "
                f"업데이트={results['updated']}, "
                f"건너뜀={results['skipped']}, "
                f"오류={results['errors']}"
            )

        except Exception as e:
            self.logger.error(
                f"CSV 파일 읽기 오류: {str(e)}",
                exc_info=True
            )
            results['errors'] = 1
            results['error_details'].append(f"CSV 파일 읽기 오류: {str(e)}")

        return results


class DCInsideCollectorService:
    """
    DC Inside 갤러리 수집 서비스 클래스
    
    DC Inside 갤러리에서 게시글을 수집하여 데이터베이스에 저장하는 서비스입니다.
    dcapi 패키지를 사용하여 웹 스크래핑을 수행합니다.
    
    주요 기능:
    1. 갤러리 글 목록 수집
    2. 개별 게시글 상세 정보 수집
    3. 중복 수집 방지 (URL 기반)
    4. 수집 작업 로그 기록
    
    사용 예시:
        collector = DCInsideCollectorService()
        result = collector.collect_from_source(source_id=1)
    """
    
    def __init__(self):
        """DC Inside 수집 서비스 초기화"""
        self.logger = logging.getLogger(__name__)
        try:
            import dcapi
            self.dcapi = dcapi
        except ImportError:
            self.logger.error("dcapi 패키지가 설치되지 않았습니다.")
            raise ImportError("dcapi 패키지를 설치하세요: pip install git+https://github.com/Limsunoh/dcinside-read-api.git")
    
    def collect_from_source(
        self,
        source: Optional[SocialMediaSource] = None,
        source_id: Optional[int] = None
    ) -> Dict:
        """
        DC Inside 소스에서 게시글을 수집합니다.
        
        Args:
            source: SocialMediaSource 객체 (선택)
            source_id: SocialMediaSource ID (선택)
            
        Returns:
            수집 결과 딕셔너리:
            {
                'status': 'success' | 'error',
                'source': 소스 이름,
                'items_collected': 수집된 게시글 수,
                'items_skipped': 건너뛴 게시글 수,
                'items_error': 오류 발생 게시글 수,
                'error_message': 에러 메시지 (있는 경우)
            }
        """
        # 소스 가져오기
        if source_id:
            try:
                source = SocialMediaSource.objects.get(id=source_id, platform='dcinside')
            except SocialMediaSource.DoesNotExist:
                error_msg = f"DC Inside 소스를 찾을 수 없습니다 (ID: {source_id})"
                self.logger.error(error_msg)
                return {
                    'status': 'error',
                    'error_message': error_msg,
                    'items_collected': 0,
                    'items_skipped': 0,
                    'items_error': 0
                }
        
        if not source:
            error_msg = "소스가 제공되지 않았습니다."
            self.logger.error(error_msg)
            return {
                'status': 'error',
                'error_message': error_msg,
                'items_collected': 0,
                'items_skipped': 0,
                'items_error': 0
            }
        
        if source.platform != 'dcinside':
            error_msg = f"DC Inside 소스가 아닙니다 (플랫폼: {source.platform})"
            self.logger.error(error_msg)
            return {
                'status': 'error',
                'error_message': error_msg,
                'items_collected': 0,
                'items_skipped': 0,
                'items_error': 0
            }
        
        # 갤러리 이름 (identifier에서 가져오기)
        gall_name = source.identifier
        
        self.logger.info(f"DC Inside 수집 시작: {source.display_name} (갤러리: {gall_name})")
        
        items_collected = 0
        items_skipped = 0
        items_error = 0
        
        try:
            # 1. 갤러리 글 목록 가져오기 (최근 1-3페이지)
            title_data = self.dcapi.read.title(gall_name, start_page=1, end_page=3)
            
            if not title_data:
                self.logger.warning(f"갤러리 '{gall_name}'에서 글 목록을 가져올 수 없습니다.")
                return {
                    'status': 'error',
                    'source': str(source),
                    'error_message': '글 목록을 가져올 수 없습니다.',
                    'items_collected': 0,
                    'items_skipped': 0,
                    'items_error': 0
                }
            
            # 2. 각 게시글 상세 정보 수집
            for page_num, posts in title_data.items():
                if not posts:
                    continue
                
                for post_info in posts:
                    post_num = post_info.get('post_num')
                    if not post_num:
                        continue
                    
                    try:
                        # 게시글 상세 정보 가져오기
                        post_data = self.dcapi.read.post(gall_name, post_num)
                        
                        if not post_data:
                            items_error += 1
                            continue
                        
                        # URL 생성
                        post_url = f"http://gall.dcinside.com/board/view/?id={gall_name}&no={post_num}&page=1"
                        
                        # 중복 체크 (URL 기반)
                        if SocialMediaPost.objects.filter(url=post_url).exists():
                            items_skipped += 1
                            continue
                        
                        # published_at 파싱
                        published_at = None
                        if post_data.get('time'):
                            try:
                                # '2018-11-16 21:28:46' 형식 파싱
                                published_at = datetime.strptime(
                                    post_data['time'],
                                    '%Y-%m-%d %H:%M:%S'
                                )
                                published_at = timezone.make_aware(published_at)
                            except (ValueError, TypeError):
                                pass
                        
                        # 조회수 파싱
                        view_num = 0
                        if post_data.get('view_num'):
                            try:
                                view_num = int(post_data['view_num'].replace(',', ''))
                            except (ValueError, TypeError):
                                pass
                        
                        # 댓글 수 파싱
                        comment_num = 0
                        if post_data.get('comment_num'):
                            try:
                                comment_num = int(post_data['comment_num'].replace(',', ''))
                            except (ValueError, TypeError):
                                pass
                        
                        # 추천/비추천 파싱
                        up = 0
                        down = 0
                        if post_data.get('up'):
                            try:
                                up = int(post_data['up'].replace(',', ''))
                            except (ValueError, TypeError):
                                pass
                        if post_data.get('down'):
                            try:
                                down = int(post_data['down'].replace(',', ''))
                            except (ValueError, TypeError):
                                pass
                        
                        # 게시글 저장
                        SocialMediaPost.objects.create(
                            source=source,
                            platform_post_id=str(post_num),
                            url=post_url,
                            title=post_data.get('title', ''),
                            content=post_data.get('content', ''),
                            author=post_data.get('writer', ''),
                            published_at=published_at,
                            views_count=view_num,
                            comments_count=comment_num,
                            likes_count=up,  # 추천 수를 likes_count에 저장
                            shares_count=down,  # 비추천 수를 shares_count에 임시 저장
                            gall_name=gall_name,
                            post_num=str(post_num),
                            ip=post_data.get('ip', ''),
                            images=post_data.get('images', []),
                            raw_data=post_data
                        )
                        
                        items_collected += 1
                        
                    except Exception as e:
                        self.logger.error(
                            f"게시글 수집 오류 (갤러리: {gall_name}, 글번호: {post_num}): {str(e)}",
                            exc_info=True
                        )
                        items_error += 1
                        continue
            
            # 마지막 수집 시간 업데이트
            source.last_collected_at = timezone.now()
            source.save()
            
            self.logger.info(
                f"DC Inside 수집 완료: {source.display_name} "
                f"(수집: {items_collected}, 건너뜀: {items_skipped}, 오류: {items_error})"
            )
            
            return {
                'status': 'success',
                'source': str(source),
                'items_collected': items_collected,
                'items_skipped': items_skipped,
                'items_error': items_error
            }
            
        except Exception as e:
            error_msg = f"DC Inside 수집 중 오류 발생: {str(e)}"
            self.logger.error(error_msg, exc_info=True)
            return {
                'status': 'error',
                'source': str(source),
                'error_message': error_msg,
                'items_collected': items_collected,
                'items_skipped': items_skipped,
                'items_error': items_error
            }


class RedditRSSCollectorService:
    """
    Reddit RSS 피드 수집 서비스 클래스
    
    Reddit RSS 피드를 파싱하여 게시글을 수집하여 데이터베이스에 저장하는 서비스입니다.
    feedparser를 사용하여 RSS 피드를 파싱합니다.
    
    주요 기능:
    1. Reddit RSS 피드 파싱
    2. 중복 수집 방지 (URL 기반)
    3. 수집 작업 로그 기록
    
    사용 예시:
        collector = RedditRSSCollectorService()
        result = collector.collect_from_source(source_id=1)
    """
    
    def __init__(self):
        """Reddit RSS 수집 서비스 초기화"""
        self.logger = logging.getLogger(__name__)
    
    def collect_from_source(
        self,
        source: Optional[SocialMediaSource] = None,
        source_id: Optional[int] = None
    ) -> Dict:
        """
        Reddit RSS 소스에서 게시글을 수집합니다.
        
        Args:
            source: SocialMediaSource 객체 (선택)
            source_id: SocialMediaSource ID (선택)
            
        Returns:
            수집 결과 딕셔너리:
            {
                'status': 'success' | 'error',
                'source': 소스 이름,
                'items_collected': 수집된 게시글 수,
                'items_skipped': 건너뛴 게시글 수,
                'items_error': 오류 발생 게시글 수,
                'error_message': 에러 메시지 (있는 경우)
            }
        """
        # 소스 가져오기
        if source_id:
            try:
                source = SocialMediaSource.objects.get(id=source_id, platform='reddit')
            except SocialMediaSource.DoesNotExist:
                error_msg = f"Reddit 소스를 찾을 수 없습니다 (ID: {source_id})"
                self.logger.error(error_msg)
                return {
                    'status': 'error',
                    'error_message': error_msg,
                    'items_collected': 0,
                    'items_skipped': 0,
                    'items_error': 0
                }
        
        if not source:
            error_msg = "소스가 제공되지 않았습니다."
            self.logger.error(error_msg)
            return {
                'status': 'error',
                'error_message': error_msg,
                'items_collected': 0,
                'items_skipped': 0,
                'items_error': 0
            }
        
        if source.platform != 'reddit':
            error_msg = f"Reddit 소스가 아닙니다 (플랫폼: {source.platform})"
            self.logger.error(error_msg)
            return {
                'status': 'error',
                'error_message': error_msg,
                'items_collected': 0,
                'items_skipped': 0,
                'items_error': 0
            }
        
        # RSS URL 가져오기
        rss_url = source.url
        if not rss_url:
            error_msg = "RSS URL이 설정되지 않았습니다."
            self.logger.error(error_msg)
            return {
                'status': 'error',
                'error_message': error_msg,
                'items_collected': 0,
                'items_skipped': 0,
                'items_error': 0
            }
        
        # 서브레딧 이름 (identifier에서 가져오기)
        subreddit = source.identifier
        
        self.logger.info(f"Reddit RSS 수집 시작: {source.display_name} (URL: {rss_url})")
        
        items_collected = 0
        items_skipped = 0
        items_error = 0
        
        try:
            # RSS 피드 파싱
            feed = feedparser.parse(rss_url)
            
            if feed.bozo and feed.bozo_exception:
                error_msg = f"RSS 피드 파싱 오류: {str(feed.bozo_exception)}"
                self.logger.error(error_msg)
                return {
                    'status': 'error',
                    'source': str(source),
                    'error_message': error_msg,
                    'items_collected': 0,
                    'items_skipped': 0,
                    'items_error': 0
                }
            
            if not feed.entries:
                self.logger.warning(f"RSS 피드에 항목이 없습니다: {rss_url}")
                return {
                    'status': 'success',
                    'source': str(source),
                    'items_collected': 0,
                    'items_skipped': 0,
                    'items_error': 0
                }
            
            # 각 게시글 처리
            for entry in feed.entries:
                try:
                    # URL 추출
                    post_url = entry.get('link', '')
                    if not post_url:
                        items_error += 1
                        continue
                    
                    # 중복 체크 (URL 기반)
                    if SocialMediaPost.objects.filter(url=post_url).exists():
                        items_skipped += 1
                        continue
                    
                    # 게시글 ID 추출 (예: t3_1pirwx8)
                    post_id = entry.get('id', '')
                    if not post_id:
                        # URL에서 추출 시도
                        # 예: https://www.reddit.com/r/technology/comments/1pirwx8/...
                        import re
                        match = re.search(r'/comments/([^/]+)/', post_url)
                        if match:
                            post_id = f"t3_{match.group(1)}"
                    
                    # 제목 추출
                    title = entry.get('title', '').strip()
                    if not title:
                        items_error += 1
                        continue
                    
                    # 작성자 추출 (예: /u/cosmicreggae)
                    author = entry.get('author', '').strip()
                    if author.startswith('/u/'):
                        author = author[3:]  # /u/ 제거
                    
                    # 발행 시간 파싱
                    published_at = None
                    if entry.get('published'):
                        try:
                            # feedparser가 자동으로 파싱한 datetime 객체 사용
                            published_at = entry.get('published_parsed')
                            if published_at:
                                from time import struct_time
                                if isinstance(published_at, struct_time):
                                    published_at = datetime(*published_at[:6])
                                    published_at = timezone.make_aware(published_at)
                        except (ValueError, TypeError, AttributeError):
                            pass
                    
                    # 내용 추출 (HTML 형식)
                    content = entry.get('summary', '') or entry.get('description', '')
                    
                    # 썸네일 이미지 추출
                    thumbnail_url = None
                    if hasattr(entry, 'media_thumbnail'):
                        if entry.media_thumbnail:
                            thumbnail_url = entry.media_thumbnail[0].get('url', '')
                    elif hasattr(entry, 'media_content'):
                        if entry.media_content:
                            thumbnail_url = entry.media_content[0].get('url', '')
                    
                    # 카테고리에서 서브레딧 이름 추출
                    entry_subreddit = subreddit
                    if hasattr(entry, 'tags') and entry.tags:
                        for tag in entry.tags:
                            if tag.get('term'):
                                entry_subreddit = tag.get('term')
                                break
                    
                    # 게시글 저장
                    SocialMediaPost.objects.create(
                        source=source,
                        platform_post_id=post_id,
                        url=post_url,
                        title=title,
                        content=content,
                        author=author,
                        published_at=published_at,
                        subreddit=entry_subreddit,
                        thumbnail_url=thumbnail_url,
                        raw_data={
                            'id': post_id,
                            'link': post_url,
                            'title': title,
                            'author': entry.get('author', ''),
                            'published': entry.get('published', ''),
                            'updated': entry.get('updated', ''),
                            'summary': content,
                        }
                    )
                    
                    items_collected += 1
                    
                except Exception as e:
                    self.logger.error(
                        f"게시글 수집 오류 (URL: {entry.get('link', 'unknown')}): {str(e)}",
                        exc_info=True
                    )
                    items_error += 1
                    continue
            
            # 마지막 수집 시간 업데이트
            source.last_collected_at = timezone.now()
            source.save()
            
            self.logger.info(
                f"Reddit RSS 수집 완료: {source.display_name} "
                f"(수집: {items_collected}, 건너뜀: {items_skipped}, 오류: {items_error})"
            )
            
            return {
                'status': 'success',
                'source': str(source),
                'items_collected': items_collected,
                'items_skipped': items_skipped,
                'items_error': items_error
            }
            
        except Exception as e:
            error_msg = f"Reddit RSS 수집 중 오류 발생: {str(e)}"
            self.logger.error(error_msg, exc_info=True)
            return {
                'status': 'error',
                'source': str(source),
                'error_message': error_msg,
                'items_collected': items_collected,
                'items_skipped': items_skipped,
                'items_error': items_error
            }

