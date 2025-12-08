from django.db import models
from django.utils import timezone


class NewsSource(models.Model):
    """
    뉴스 소스 정보 모델
    
    RSS 피드나 API를 통해 뉴스를 수집하는 소스의 정보를 저장합니다.
    각 소스는 신문사(publisher)와 카테고리(category)를 가지며, 고유한 URL을 가집니다.
    """
    # 신문사 이름 (예: '경향신문', '조선일보' 등)
    publisher = models.CharField(
        max_length=100,
        verbose_name='신문사',
        help_text='뉴스 소스의 신문사 이름입니다. 예: 경향신문',
        db_index=True,
        default='Unknown'
    )
    
    # 카테고리 (예: '정치', '경제', '사회' 등)
    category = models.CharField(
        max_length=100,
        blank=True,
        null=True,
        verbose_name='카테고리',
        help_text='뉴스 카테고리 (예: 정치, 경제, 사회 등)',
        db_index=True
    )
    
    # RSS 피드 URL 또는 API 엔드포인트
    url = models.URLField(
        max_length=500,
        unique=True,
        verbose_name='URL',
        help_text='RSS 피드 URL 또는 API 엔드포인트 주소'
    )
    
    # 소스 타입 (RSS, API 등)
    source_type = models.CharField(
        max_length=20,
        choices=[
            ('rss', 'RSS'),
            ('api', 'API'),
            ('scraping', '웹 스크래핑'),
        ],
        default='rss',
        verbose_name='소스 타입',
        help_text='데이터 수집 방식'
    )
    
    # 활성화 여부
    is_active = models.BooleanField(
        default=True,
        verbose_name='활성화',
        help_text='이 소스에서 데이터를 수집할지 여부'
    )
    
    # 수집 주기 (분 단위)
    collection_interval = models.IntegerField(
        default=60,
        verbose_name='수집 주기(분)',
        help_text='데이터를 수집하는 주기 (분 단위)'
    )
    
    # 마지막 수집 시간
    last_collected_at = models.DateTimeField(
        null=True,
        blank=True,
        verbose_name='마지막 수집 시간',
        help_text='이 소스에서 마지막으로 데이터를 수집한 시간'
    )
    
    # 생성 시간
    created_at = models.DateTimeField(
        auto_now_add=True,
        verbose_name='생성 시간'
    )
    
    # 수정 시간
    updated_at = models.DateTimeField(
        auto_now=True,
        verbose_name='수정 시간'
    )
    
    class Meta:
        verbose_name = '뉴스 소스'
        verbose_name_plural = '뉴스 소스'
        ordering = ['publisher', 'category', '-created_at']
        # 같은 신문사의 같은 카테고리는 하나만 (URL이 다르면 별도 소스)
        unique_together = [['publisher', 'category', 'url']]
    
    def __str__(self):
        if self.category:
            return f"{self.publisher} - {self.category}"
        return f"{self.publisher}"


class NewsArticle(models.Model):
    """
    수집된 뉴스 기사 모델
    
    RSS 피드나 API를 통해 수집한 뉴스 기사의 정보를 저장합니다.
    각 기사는 고유한 URL을 가지며, 중복 수집을 방지합니다.
    """
    # 뉴스 소스 (외래키)
    source = models.ForeignKey(
        NewsSource,
        on_delete=models.CASCADE,
        related_name='articles',
        verbose_name='뉴스 소스',
        help_text='이 기사를 수집한 뉴스 소스'
    )
    
    # 기사 제목
    title = models.CharField(
        max_length=500,
        verbose_name='제목',
        help_text='뉴스 기사의 제목'
    )
    
    # 기사 URL (고유 식별자로 사용)
    url = models.URLField(
        max_length=1000,
        unique=True,
        verbose_name='URL',
        help_text='뉴스 기사의 원본 URL (중복 방지용)',
        db_index=True  # 인덱스 추가로 조회 성능 향상
    )
    
    # 기사 설명/요약
    description = models.TextField(
        blank=True,
        null=True,
        verbose_name='설명',
        help_text='뉴스 기사의 요약 또는 설명'
    )
    
    # 작성자
    author = models.CharField(
        max_length=200,
        blank=True,
        null=True,
        verbose_name='작성자',
        help_text='기사를 작성한 기자 또는 작성자'
    )
    
    # 카테고리
    category = models.CharField(
        max_length=100,
        blank=True,
        null=True,
        verbose_name='카테고리',
        help_text='기사의 카테고리 (예: 정치, 경제, 사회 등)',
        db_index=True  # 카테고리별 조회를 위한 인덱스
    )
    
    # 발행 시간 (RSS 피드에서 가져온 시간)
    published_at = models.DateTimeField(
        null=True,
        blank=True,
        verbose_name='발행 시간',
        help_text='기사가 발행된 시간 (RSS 피드에서 가져온 시간)',
        db_index=True  # 시간별 조회를 위한 인덱스
    )
    
    # 수집 시간
    collected_at = models.DateTimeField(
        auto_now_add=True,
        verbose_name='수집 시간',
        help_text='이 기사를 수집한 시간',
        db_index=True
    )
    
    # 처리 여부 (분석 완료 여부)
    is_processed = models.BooleanField(
        default=False,
        verbose_name='처리 완료',
        help_text='이 기사가 분석 처리되었는지 여부'
    )
    
    class Meta:
        verbose_name = '뉴스 기사'
        verbose_name_plural = '뉴스 기사'
        ordering = ['-published_at', '-collected_at']
        indexes = [
            models.Index(fields=['-published_at', '-collected_at']),  # 복합 인덱스
            models.Index(fields=['source', '-published_at']),  # 소스별 최신 기사 조회용
        ]
    
    def __str__(self):
        return f"{self.title[:50]}... ({str(self.source)})"


class SocialMediaPost(models.Model):
    """소셜 미디어 게시물"""
    # TODO: 필드 정의
    pass


class DataCollectionJob(models.Model):
    """
    데이터 수집 작업 로그 모델
    
    각 데이터 수집 작업의 실행 기록을 저장합니다.
    작업 성공/실패 여부, 수집한 데이터 개수 등을 추적합니다.
    """
    # 작업 상태 선택지
    STATUS_CHOICES = [
        ('pending', '대기 중'),
        ('running', '실행 중'),
        ('completed', '완료'),
        ('failed', '실패'),
    ]
    
    # 뉴스 소스 (외래키, 선택적)
    source = models.ForeignKey(
        NewsSource,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='collection_jobs',
        verbose_name='뉴스 소스',
        help_text='이 작업이 실행된 뉴스 소스'
    )
    
    # 작업 상태
    status = models.CharField(
        max_length=20,
        choices=STATUS_CHOICES,
        default='pending',
        verbose_name='상태',
        help_text='작업 상태 (pending: 대기 중, running: 실행 중, completed: 완료, failed: 실패)'
    )
    
    # 시작 시간
    started_at = models.DateTimeField(
        auto_now_add=True,
        verbose_name='시작 시간',
        help_text='작업이 시작된 시간'
    )
    
    # 완료 시간
    completed_at = models.DateTimeField(
        null=True,
        blank=True,
        verbose_name='완료 시간',
        help_text='작업이 완료된 시간'
    )
    
    # 수집한 데이터 개수
    items_collected = models.IntegerField(
        default=0,
        verbose_name='수집 개수',
        help_text='이 작업에서 수집한 데이터 개수'
    )
    
    # 에러 메시지 (실패한 경우)
    error_message = models.TextField(
        blank=True,
        null=True,
        verbose_name='에러 메시지',
        help_text='작업이 실패한 경우 에러 메시지'
    )
    
    class Meta:
        verbose_name = '데이터 수집 작업'
        verbose_name_plural = '데이터 수집 작업'
        ordering = ['-started_at']
    
    def __str__(self):
        source_name = str(self.source) if self.source else 'Unknown'
        return f"{source_name} - {self.get_status_display()} ({self.started_at})"


class CollectionSession(models.Model):
    """
    전체 수집 세션 모델
    
    전체 NewsSource 수집 작업의 요약 정보를 저장합니다.
    언제 시작했고, 언제 끝났는지, 몇 개의 소스를 처리했는지 등의 통계를 기록합니다.
    """
    # 세션 상태 선택지
    STATUS_CHOICES = [
        ('running', '실행 중'),
        ('completed', '완료'),
        ('failed', '실패'),
        ('cancelled', '취소됨'),
    ]
    
    # 시작 시간
    started_at = models.DateTimeField(
        auto_now_add=True,
        verbose_name='시작 시간',
        help_text='수집 세션이 시작된 시간',
        db_index=True
    )
    
    # 완료 시간
    completed_at = models.DateTimeField(
        null=True,
        blank=True,
        verbose_name='완료 시간',
        help_text='수집 세션이 완료된 시간'
    )
    
    # 세션 상태
    status = models.CharField(
        max_length=20,
        choices=STATUS_CHOICES,
        default='running',
        verbose_name='상태',
        help_text='세션 상태'
    )
    
    # 총 소스 수
    total_sources = models.IntegerField(
        default=0,
        verbose_name='총 소스 수',
        help_text='처리 대상인 총 NewsSource 개수'
    )
    
    # 성공한 소스 수
    successful_sources = models.IntegerField(
        default=0,
        verbose_name='성공한 소스 수',
        help_text='성공적으로 수집 완료된 소스 개수'
    )
    
    # 실패한 소스 수
    failed_sources = models.IntegerField(
        default=0,
        verbose_name='실패한 소스 수',
        help_text='수집에 실패한 소스 개수'
    )
    
    # 총 수집된 기사 수
    total_articles_collected = models.IntegerField(
        default=0,
        verbose_name='총 수집 기사 수',
        help_text='이 세션에서 수집된 총 NewsArticle 개수'
    )
    
    # 건너뛴 기사 수 (중복 등)
    total_articles_skipped = models.IntegerField(
        default=0,
        verbose_name='건너뛴 기사 수',
        help_text='중복 등으로 건너뛴 기사 개수'
    )
    
    # 오류 발생 기사 수
    total_articles_error = models.IntegerField(
        default=0,
        verbose_name='오류 기사 수',
        help_text='저장 중 오류가 발생한 기사 개수'
    )
    
    # 소요 시간 (초)
    duration_seconds = models.FloatField(
        null=True,
        blank=True,
        verbose_name='소요 시간 (초)',
        help_text='세션 시작부터 완료까지 소요된 시간'
    )
    
    # 리포트 파일 경로 (JSON, 마크다운)
    json_report_path = models.CharField(
        max_length=500,
        blank=True,
        null=True,
        verbose_name='JSON 리포트 경로',
        help_text='생성된 JSON 리포트 파일 경로'
    )
    
    # 마크다운 리포트 경로
    markdown_report_path = models.CharField(
        max_length=500,
        blank=True,
        null=True,
        verbose_name='마크다운 리포트 경로',
        help_text='생성된 마크다운 리포트 파일 경로'
    )
    
    # 메모/설명
    notes = models.TextField(
        blank=True,
        null=True,
        verbose_name='메모',
        help_text='세션에 대한 추가 메모'
    )
    
    class Meta:
        verbose_name = '수집 세션'
        verbose_name_plural = '수집 세션'
        ordering = ['-started_at']
        indexes = [
            models.Index(fields=['-started_at']),
            models.Index(fields=['status', '-started_at']),
        ]
    
    def __str__(self):
        return f"수집 세션 #{self.id} - {self.get_status_display()} ({self.started_at})"
    
    def calculate_duration(self):
        """소요 시간 계산"""
        if self.completed_at and self.started_at:
            delta = self.completed_at - self.started_at
            self.duration_seconds = delta.total_seconds()
            return self.duration_seconds
        return None
    
    def mark_completed(self):
        """세션 완료 처리"""
        self.completed_at = timezone.now()
        self.status = 'completed'
        self.calculate_duration()
        self.save()
    
    def get_summary(self):
        """세션 요약 정보 반환"""
        return {
            'id': self.id,
            'started_at': self.started_at.isoformat() if self.started_at else None,
            'completed_at': self.completed_at.isoformat() if self.completed_at else None,
            'status': self.status,
            'total_sources': self.total_sources,
            'successful_sources': self.successful_sources,
            'failed_sources': self.failed_sources,
            'total_articles_collected': self.total_articles_collected,
            'total_articles_skipped': self.total_articles_skipped,
            'total_articles_error': self.total_articles_error,
            'duration_seconds': self.duration_seconds,
            'json_report_path': self.json_report_path,
            'markdown_report_path': self.markdown_report_path,
        }
