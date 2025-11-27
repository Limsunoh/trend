"""
Django Admin 설정

이 모듈은 data_collector 앱의 모델들을 Django Admin에서 관리할 수 있도록 설정합니다.
Django Admin은 웹 브라우저를 통해 데이터를 확인하고 관리할 수 있는 관리자 인터페이스입니다.
"""
from django.contrib import admin
from django.utils.html import format_html
from django.urls import reverse
from .models import NewsSource, NewsArticle, SocialMediaPost, DataCollectionJob


@admin.register(NewsSource)
class NewsSourceAdmin(admin.ModelAdmin):
    """
    뉴스 소스 관리 클래스
    
    Django Admin에서 뉴스 소스를 관리할 때 표시되는 내용과 동작을 정의합니다.
    """
    # 목록 페이지에 표시할 필드들
    list_display = [
        'name',           # 소스 이름
        'source_type',    # 소스 타입 (RSS, API 등)
        'is_active',      # 활성화 여부
        'collection_interval',  # 수집 주기
        'last_collected_at',    # 마지막 수집 시간
        'article_count',        # 수집된 기사 개수 (커스텀 메서드)
        'created_at',     # 생성 시간
    ]
    
    # 필터링 옵션 (우측 사이드바)
    list_filter = [
        'source_type',    # 소스 타입별 필터
        'is_active',      # 활성화 상태별 필터
        'created_at',     # 생성 시간별 필터
    ]
    
    # 검색 가능한 필드
    search_fields = [
        'name',  # 소스 이름으로 검색
        'url',   # URL로 검색
    ]
    
    # 필드 그룹화 (상세 페이지)
    fieldsets = (
        ('기본 정보', {
            'fields': ('name', 'url', 'source_type')
        }),
        ('수집 설정', {
            'fields': ('is_active', 'collection_interval')
        }),
        ('수집 정보', {
            'fields': ('last_collected_at',),
            'classes': ('collapse',)  # 접을 수 있는 섹션
        }),
        ('시간 정보', {
            'fields': ('created_at', 'updated_at'),
            'classes': ('collapse',)
        }),
    )
    
    # 읽기 전용 필드 (자동으로 설정되는 필드들)
    readonly_fields = ['created_at', 'updated_at', 'last_collected_at']
    
    # 커스텀 메서드: 수집된 기사 개수 표시
    def article_count(self, obj):
        """
        이 소스에서 수집된 기사 개수를 반환합니다.
        """
        count = obj.articles.count()
        if count > 0:
            # 클릭 가능한 링크로 표시
            url = reverse('admin:data_collector_newsarticle_changelist')
            url += f'?source__id__exact={obj.id}'
            return format_html('<a href="{}">{}개</a>', url, count)
        return '0개'
    
    article_count.short_description = '수집된 기사 수'  # 컬럼 헤더 이름


@admin.register(NewsArticle)
class NewsArticleAdmin(admin.ModelAdmin):
    """
    뉴스 기사 관리 클래스
    
    Django Admin에서 수집된 뉴스 기사를 관리할 때 표시되는 내용과 동작을 정의합니다.
    """
    # 목록 페이지에 표시할 필드들
    list_display = [
        'title_short',      # 제목 (짧게)
        'source',           # 소스
        'category',         # 카테고리
        'author',           # 작성자
        'published_at',     # 발행 시간
        'collected_at',     # 수집 시간
        'is_processed',     # 처리 완료 여부
        'url_link',         # 원본 URL 링크 (커스텀 메서드)
    ]
    
    # 필터링 옵션
    list_filter = [
        'source',           # 소스별 필터
        'category',         # 카테고리별 필터
        'is_processed',     # 처리 상태별 필터
        'published_at',     # 발행 시간별 필터
        'collected_at',     # 수집 시간별 필터
    ]
    
    # 검색 가능한 필드
    search_fields = [
        'title',        # 제목으로 검색
        'description',  # 설명으로 검색
        'author',       # 작성자로 검색
        'url',          # URL로 검색
    ]
    
    # 날짜 계층 구조 (발행 시간 기준)
    date_hierarchy = 'published_at'
    
    # 페이지당 항목 수
    list_per_page = 50
    
    # 읽기 전용 필드
    readonly_fields = ['collected_at', 'url']
    
    # 필드 그룹화
    fieldsets = (
        ('기본 정보', {
            'fields': ('source', 'title', 'url', 'category')
        }),
        ('내용', {
            'fields': ('description', 'content', 'author')
        }),
        ('시간 정보', {
            'fields': ('published_at', 'collected_at')
        }),
        ('상태', {
            'fields': ('is_processed',)
        }),
    )
    
    # 커스텀 메서드: 제목을 짧게 표시
    def title_short(self, obj):
        """
        제목을 50자로 제한하여 표시합니다.
        """
        if len(obj.title) > 50:
            return obj.title[:50] + '...'
        return obj.title
    
    title_short.short_description = '제목'
    
    # 커스텀 메서드: URL을 클릭 가능한 링크로 표시
    def url_link(self, obj):
        """
        원본 기사 URL을 클릭 가능한 링크로 표시합니다.
        """
        return format_html('<a href="{}" target="_blank">링크</a>', obj.url)
    
    url_link.short_description = '원본 링크'


@admin.register(DataCollectionJob)
class DataCollectionJobAdmin(admin.ModelAdmin):
    """
    데이터 수집 작업 로그 관리 클래스
    
    Django Admin에서 수집 작업 로그를 관리할 때 표시되는 내용과 동작을 정의합니다.
    """
    # 목록 페이지에 표시할 필드들
    list_display = [
        'id',                    # 작업 ID
        'source',                # 소스
        'status_colored',        # 상태 (컬러 표시)
        'items_collected',       # 수집 개수
        'started_at',            # 시작 시간
        'completed_at',          # 완료 시간
        'duration',              # 소요 시간 (커스텀 메서드)
    ]
    
    # 필터링 옵션
    list_filter = [
        'status',                # 상태별 필터
        'source',                # 소스별 필터
        'started_at',            # 시작 시간별 필터
    ]
    
    # 검색 가능한 필드
    search_fields = [
        'source__name',          # 소스 이름으로 검색
        'error_message',         # 에러 메시지로 검색
    ]
    
    # 날짜 계층 구조
    date_hierarchy = 'started_at'
    
    # 읽기 전용 필드
    readonly_fields = [
        'source',
        'status',
        'started_at',
        'completed_at',
        'items_collected',
        'error_message',
    ]
    
    # 필드 그룹화
    fieldsets = (
        ('작업 정보', {
            'fields': ('source', 'status', 'items_collected')
        }),
        ('시간 정보', {
            'fields': ('started_at', 'completed_at')
        }),
        ('에러 정보', {
            'fields': ('error_message',),
            'classes': ('collapse',)
        }),
    )
    
    # 추가/수정 금지 (로그는 읽기 전용)
    def has_add_permission(self, request):
        return False
    
    def has_change_permission(self, request, obj=None):
        return False
    
    # 커스텀 메서드: 상태를 컬러로 표시
    def status_colored(self, obj):
        """
        작업 상태를 색상으로 구분하여 표시합니다.
        """
        colors = {
            'pending': '#gray',
            'running': '#blue',
            'completed': '#green',
            'failed': '#red',
        }
        color = colors.get(obj.status, '#black')
        status_display = obj.get_status_display()
        return format_html(
            '<span style="color: {}; font-weight: bold;">{}</span>',
            color,
            status_display
        )
    
    status_colored.short_description = '상태'
    
    # 커스텀 메서드: 작업 소요 시간 계산
    def duration(self, obj):
        """
        작업 소요 시간을 계산하여 표시합니다.
        """
        if obj.started_at and obj.completed_at:
            delta = obj.completed_at - obj.started_at
            total_seconds = int(delta.total_seconds())
            minutes = total_seconds // 60
            seconds = total_seconds % 60
            return f"{minutes}분 {seconds}초"
        elif obj.started_at:
            return "진행 중..."
        return "-"
    
    duration.short_description = '소요 시간'


# SocialMediaPost는 아직 구현되지 않았으므로 기본 Admin만 등록
@admin.register(SocialMediaPost)
class SocialMediaPostAdmin(admin.ModelAdmin):
    """
    소셜 미디어 게시물 관리 클래스 (TODO)
    
    현재는 기본 Admin 설정만 되어 있습니다.
    모델이 구현되면 추가 설정이 필요합니다.
    """
    pass
