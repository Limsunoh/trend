"""
Django REST Framework Serializers 모듈

이 모듈은 data_collector 앱의 모델들을 JSON 형태로 직렬화/역직렬화하는
Serializer 클래스들을 정의합니다.

Serializer의 역할:
1. 직렬화 (Serialization): Django 모델 객체 → JSON (API 응답)
2. 역직렬화 (Deserialization): JSON → Django 모델 객체 (API 요청)

사용 목적:
- REST API를 통한 데이터 조회 (GET)
- REST API를 통한 데이터 생성/수정 (POST, PUT, PATCH)
- 데이터 검증 (Validation)
- 중첩된 관계 표현 (Nested Relationships)
"""

from typing import Any, Dict, Optional

from rest_framework import serializers

from .models import (
    DataCollectionJob,
    NewsArticle,
    NewsSource,
    SocialMediaPost,
    SocialMediaSource,
)


class NewsSourceSerializer(serializers.ModelSerializer):
    """
    뉴스 소스 Serializer

    NewsSource 모델을 JSON으로 변환하거나, JSON으로부터 NewsSource 객체를 생성합니다.

    주요 기능:
    - 뉴스 소스 정보 직렬화/역직렬화
    - 수집된 기사 개수 표시 (읽기 전용)
    - 자동 생성 필드는 읽기 전용으로 설정

    사용 예시:
        # 직렬화 (모델 → JSON)
        source = NewsSource.objects.get(id=1)
        serializer = NewsSourceSerializer(source)
        json_data = serializer.data
        # {'id': 1, 'name': '경향신문', 'url': '...', ...}

        # 역직렬화 (JSON → 모델)
        data = {'name': '조선일보', 'url': 'https://...', 'source_type': 'rss'}
        serializer = NewsSourceSerializer(data=data)
        if serializer.is_valid():
            source = serializer.save()  # 모델 객체 생성
    """

    # 읽기 전용 필드: 수집된 기사 개수
    # 실제 모델 필드는 아니지만, 관련 기사 개수를 계산하여 표시합니다.
    article_count = serializers.IntegerField(
        read_only=True, help_text="이 소스에서 수집된 기사 개수"
    )

    # 읽기 전용 필드: 마지막 수집 시간 (형식화)
    last_collected_at_display = serializers.DateTimeField(
        read_only=True,
        source="last_collected_at",
        format="%Y-%m-%d %H:%M:%S",
        help_text="마지막 수집 시간 (형식화된 문자열)",
    )

    class Meta:
        """
        Serializer 메타 클래스

        이 클래스는 Serializer의 동작을 정의합니다.
        - model: 직렬화할 Django 모델
        - fields: 직렬화에 포함할 필드들
        - read_only_fields: 읽기 전용 필드들 (API에서 수정 불가)
        - extra_kwargs: 필드별 추가 설정
        """

        model = NewsSource  # 연동할 Django 모델

        # 직렬화에 포함할 모든 필드
        # '__all__'을 사용하면 모델의 모든 필드를 포함합니다.
        fields = "__all__"

        # 읽기 전용 필드들
        # 이 필드들은 API 요청으로 생성/수정할 수 없습니다.
        # (데이터베이스나 코드에서만 설정)
        read_only_fields = [
            "id",  # ID는 자동 생성
            "created_at",  # 생성 시간은 자동 설정
            "updated_at",  # 수정 시간은 자동 설정
            "last_collected_at",  # 마지막 수집 시간은 수집 작업에서 설정
        ]

        # 필드별 추가 설정
        extra_kwargs = {
            "name": {
                "help_text": "뉴스 소스의 이름 (예: 경향신문, 조선일보)",
                "required": True,  # 필수 필드
            },
            "url": {
                "help_text": "RSS 피드 URL 또는 API 엔드포인트 주소",
                "required": True,  # 필수 필드
            },
            "source_type": {
                "help_text": "데이터 수집 방식 (rss, api, scraping)",
                "required": False,  # 기본값이 있으므로 선택
            },
            "is_active": {
                "help_text": "이 소스에서 데이터를 수집할지 여부",
                "required": False,  # 기본값(True)이 있으므로 선택
            },
            "collection_interval": {
                "help_text": "데이터 수집 주기 (분 단위)",
                "required": False,  # 기본값(60)이 있으므로 선택
                "min_value": 1,  # 최소값 1분
                "max_value": 1440,  # 최대값 24시간(1440분)
            },
        }

    def validate(self, data: Dict[str, Any]) -> Dict[str, Any]:
        """
        전체 데이터 검증 메서드

        모든 필드를 하나의 메서드에서 검증합니다.
        data는 딕셔너리 형태로 모든 필드 값이 포함되어 있습니다.

        개별 필드 검증 메서드(validate_name, validate_url) 대신
        이 메서드 하나에서 모든 검증을 수행합니다.

        Args:
            data: 검증할 전체 데이터 딕셔너리
                예: {'name': '경향신문', 'url': 'https://...', 'source_type': 'rss'...}

        Returns:
            검증된 데이터 딕셔너리 (필요시 값 수정 후 반환)

        Raises:
            serializers.ValidationError: 검증 실패 시
                딕셔너리 형태로 필드별 에러 메시지 지정 가능
                예: {'name': '소스 이름은 필수입니다.', 'url': 'URL 형식이 올바르지 않습니다.'}
        """
        # name 필드 검증 및 정리
        if "name" in data:
            name = data.get("name", "")
            # 문자열인 경우에만 strip() 적용
            if isinstance(name, str):
                name = name.strip()

            # 이름이 비어있는지 확인
            if not name:
                raise serializers.ValidationError({"name": "소스 이름은 필수입니다."})

            # 검증된 이름을 딕셔너리에 다시 저장 (공백 제거된 값)
            data["name"] = name

        # url 필드 검증
        if "url" in data:
            url = data.get("url", "")
            # 문자열인 경우에만 strip() 적용
            if isinstance(url, str):
                url = url.strip()

            # URL이 비어있는지 확인
            if not url:
                raise serializers.ValidationError({"url": "URL은 필수입니다."})

            # URL 형식 검증 (http:// 또는 https://로 시작하는지 확인)
            if not (url.startswith("http://") or url.startswith("https://")):
                raise serializers.ValidationError(
                    {"url": "URL은 http:// 또는 https://로 시작해야 합니다."}
                )

            # 검증된 URL을 딕셔너리에 다시 저장
            data["url"] = url

        # 모든 검증 통과 시 검증된 데이터 딕셔너리 반환
        return data

    def to_representation(self, instance):
        """
        직렬화 시 추가 데이터를 포함하는 메서드

        모델 필드 외에 추가 정보(예: 관련 기사 개수)를 포함할 수 있습니다.

        Args:
            instance: 직렬화할 모델 인스턴스

        Returns:
            직렬화된 딕셔너리
        """
        # 기본 직렬화 수행
        representation = super().to_representation(instance)

        # 수집된 기사 개수 추가
        # instance.articles는 related_name='articles'로 정의된 역참조입니다.
        representation["article_count"] = instance.articles.count()

        return representation


class NewsArticleSerializer(serializers.ModelSerializer):
    """
    뉴스 기사 Serializer

    NewsArticle 모델을 JSON으로 변환하거나, JSON으로부터 NewsArticle 객체를 생성합니다.

    주요 기능:
    - 뉴스 기사 정보 직렬화/역직렬화
    - 소스 정보 중첩 표시 (nested representation)
    - 제목, 설명 등의 검증

    사용 예시:
        # 직렬화
        article = NewsArticle.objects.get(id=1)
        serializer = NewsArticleSerializer(article)
        json_data = serializer.data

        # 소스 정보를 포함한 직렬화
        serializer = NewsArticleSerializer(article, include_source=True)
    """

    # 중첩된 소스 정보
    # ForeignKey 필드를 중첩된 객체로 표시합니다.
    # source 필드는 소스 ID만 표시하지만, source_detail은 전체 소스 정보를 포함합니다.
    source_detail = NewsSourceSerializer(
        source="source", read_only=True, help_text="뉴스 소스 상세 정보"
    )

    # 소스 이름 (간단한 참조)
    # 소스의 전체 정보가 필요 없을 때는 이름만 표시
    source_name = serializers.SerializerMethodField(
        read_only=True, help_text="뉴스 소스 이름"
    )

    def get_source_name(self, obj: NewsArticle) -> str:
        return str(obj.source) if obj.source else "Unknown"

    # 제목 요약 (긴 제목을 짧게)
    title_short = serializers.SerializerMethodField(
        help_text="제목 요약 (50자로 제한)",
    )

    # 발행 시간 형식화 (한글/로컬 표시용)

    # 발행 시간 형식화 (한글/로컬 표시용)
    published_at_display = serializers.DateTimeField(
        read_only=True,
        source="published_at",
        format="%Y-%m-%d %H:%M:%S",
        help_text="발행 시간 (형식화된 문자열)",
    )

    # 수집 시간 형식화 (한글/로컬 표시용)
    collected_at_display = serializers.DateTimeField(
        read_only=True,
        source="collected_at",
        format="%Y-%m-%d %H:%M:%S",
        help_text="수집 시간 (형식화된 문자열)",
    )

    class Meta:
        """
        Serializer 메타 클래스
        """

        model = NewsArticle

        # 모든 필드 포함
        fields = "__all__"

        # 읽기 전용 필드들
        read_only_fields = [
            "id",  # ID는 자동 생성
            "collected_at",  # 수집 시간은 자동 설정
            "url",  # URL은 수집 시 자동 설정되므로 수정 불가
        ]

        # 필드별 추가 설정
        extra_kwargs = {
            "title": {
                "help_text": "뉴스 기사의 제목",
                "required": True,
                "max_length": 500,
            },
            "source": {
                "help_text": "뉴스 소스 ID",
                "required": True,
            },
            "description": {
                "help_text": "뉴스 기사의 요약 또는 설명",
                "required": False,
                "allow_blank": True,
                "allow_null": True,
            },
            "author": {
                "help_text": "기사를 작성한 기자 또는 작성자",
                "required": False,
                "allow_blank": True,
                "allow_null": True,
                "max_length": 200,
            },
            "category": {
                "help_text": "기사의 카테고리 (예: 정치, 경제, 사회 등)",
                "required": False,
                "allow_blank": True,
                "allow_null": True,
                "max_length": 100,
            },
            "published_at": {
                "help_text": "기사가 발행된 시간",
                "required": False,
                "allow_null": True,
            },
            "is_processed": {
                "help_text": "이 기사가 분석 처리되었는지 여부",
                "required": False,
            },
        }

    def get_title_short(self, obj: NewsArticle) -> str:
        """
        제목을 50자로 제한하여 반환하는 메서드

        SerializerMethodField를 사용할 때 필요한 메서드입니다.
        'get_필드명' 형식으로 메서드 이름을 지정합니다.

        Args:
            obj: 직렬화할 모델 인스턴스 (NewsArticle)

        Returns:
            50자로 제한된 제목 문자열
        """
        if obj.title and len(obj.title) > 50:
            return obj.title[:50] + "..."
        return obj.title or ""

    def validate(self, data: Dict[str, Any]) -> Dict[str, Any]:
        """
        전체 데이터 검증 메서드

        모든 필드를 하나의 메서드에서 검증합니다.
        data는 딕셔너리 형태로 모든 필드 값이 포함되어 있습니다.

        Args:
            data: 검증할 전체 데이터 딕셔너리
                예: {'title': '기사 제목', 'url': 'https://...', 'source': 1, ...}

        Returns:
            검증된 데이터 딕셔너리 (필요시 값 수정 후 반환)

        Raises:
            serializers.ValidationError: 검증 실패 시
                딕셔너리 형태로 필드별 에러 메시지 지정 가능
                예: {'title': '제목은 필수입니다.', 'url': 'URL 형식이 올바르지 않습니다.'}
        """
        # title 필드 검증 및 정리
        if "title" in data:
            title = data.get("title", "")
            # 문자열인 경우에만 strip() 적용
            if isinstance(title, str):
                title = title.strip()

            # 제목이 비어있는지 확인
            if not title:
                raise serializers.ValidationError({"title": "제목은 필수입니다."})

            # 검증된 제목을 딕셔너리에 다시 저장 (공백 제거된 값)
            data["title"] = title

        # url 필드 검증
        if "url" in data:
            url = data.get("url", "")
            # url이 제공된 경우에만 검증 (수정 시에는 선택적일 수 있음)
            if url:
                # 문자열인 경우에만 strip() 적용
                if isinstance(url, str):
                    url = url.strip()

                # URL 형식 검증 (http:// 또는 https://로 시작하는지 확인)
                if not (url.startswith("http://") or url.startswith("https://")):
                    raise serializers.ValidationError(
                        {"url": "URL은 http:// 또는 https://로 시작해야 합니다."}
                    )

                # 검증된 URL을 딕셔너리에 다시 저장
                data["url"] = url

        # 모든 검증 통과 시 검증된 데이터 딕셔너리 반환
        return data


class DataCollectionJobSerializer(serializers.ModelSerializer):
    """
    데이터 수집 작업 로그 Serializer

    DataCollectionJob 모델을 JSON으로 변환합니다.
    수집 작업 로그는 읽기 전용이므로 역직렬화는 지원하지 않습니다.

    주요 기능:
    - 수집 작업 로그 정보 직렬화
    - 소스 정보 포함
    - 작업 소요 시간 계산
    - 상태 표시

    사용 예시:
        # 직렬화
        job = DataCollectionJob.objects.get(id=1)
        serializer = DataCollectionJobSerializer(job)
        json_data = serializer.data
    """

    # 소스 정보 (중첩) - GenericForeignKey에 맞게 수정
    source_detail = serializers.SerializerMethodField(
        help_text="소스 상세 정보 (NewsSource 또는 SocialMediaSource)"
    )

    # 소스 타입
    source_type = serializers.SerializerMethodField(
        help_text="소스 타입 (news 또는 social_media)"
    )

    # 소스 이름
    source_name = serializers.SerializerMethodField(
        help_text='소스 이름 (소스가 삭제된 경우 "Unknown")'
    )

    # 상태 표시 이름
    # choices 필드의 실제 표시 이름을 반환합니다.
    status_display = serializers.CharField(
        source="get_status_display",
        read_only=True,
        help_text='작업 상태 표시 이름 (예: "완료", "실패")',
    )

    # 작업 소요 시간
    duration = serializers.SerializerMethodField(
        help_text="작업 소요 시간 (분:초 형식)"
    )

    # 시작 시간 형식화
    started_at_display = serializers.DateTimeField(
        read_only=True,
        source="started_at",
        format="%Y-%m-%d %H:%M:%S",
        help_text="시작 시간 (형식화된 문자열)",
    )

    # 완료 시간 형식화
    completed_at_display = serializers.DateTimeField(
        read_only=True,
        source="completed_at",
        format="%Y-%m-%d %H:%M:%S",
        help_text="완료 시간 (형식화된 문자열, 완료되지 않은 경우 None)",
    )

    class Meta:
        """
        Serializer 메타 클래스
        """

        model = DataCollectionJob

        # 모든 필드 포함
        fields = "__all__"

        # 모든 필드를 읽기 전용으로 설정
        # 수집 작업 로그는 수집 작업에서만 생성되므로,
        # API를 통해 직접 생성/수정할 수 없도록 합니다.
        read_only_fields = [
            "id",
            "source",
            "status",
            "started_at",
            "completed_at",
            "items_collected",
            "error_message",
        ]
        extra_kwargs = {}

    def get_source_detail(self, obj: DataCollectionJob) -> Optional[Dict[str, Any]]:
        """
        소스 상세 정보를 반환하는 메서드 (GenericForeignKey 지원)

        Args:
            obj: 직렬화할 모델 인스턴스 (DataCollectionJob)

        Returns:
            NewsSource 또는 SocialMediaSource의 직렬화된 데이터
        """
        if not obj.source:
            return None

        # 소스 타입에 따라 적절한 Serializer 사용
        if obj.content_type and obj.content_type.model == "newssource":
            return NewsSourceSerializer(obj.source).data
        elif obj.content_type and obj.content_type.model == "socialmediasource":
            # SocialMediaSourceSerializer는 같은 파일에 정의되어 있음
            return SocialMediaSourceSerializer(obj.source).data

        return None

    def get_source_type(self, obj: DataCollectionJob) -> Optional[str]:
        """소스 타입 반환 (news 또는 social_media)"""
        return obj.source_type

    def get_source_name(self, obj: DataCollectionJob) -> str:
        """
        소스 이름을 반환하는 메서드

        소스가 삭제된 경우 None일 수 있으므로 안전하게 처리합니다.

        Args:
            obj: 직렬화할 모델 인스턴스 (DataCollectionJob)

        Returns:
            소스 이름 또는 "Unknown"
        """
        return str(obj.source) if obj.source else "Unknown"

    def get_duration(self, obj: DataCollectionJob) -> str:
        """
        작업 소요 시간을 계산하여 반환하는 메서드

        Args:
            obj: 직렬화할 모델 인스턴스 (DataCollectionJob)

        Returns:
            작업 소요 시간 문자열 (예: "5분 30초") 또는 "진행 중..." 또는 "-"
        """
        if obj.started_at and obj.completed_at:
            # 완료된 작업: 소요 시간 계산
            delta = obj.completed_at - obj.started_at
            total_seconds = int(delta.total_seconds())
            minutes = total_seconds // 60
            seconds = total_seconds % 60
            return f"{minutes}분 {seconds}초"
        elif obj.started_at:
            # 진행 중인 작업
            return "진행 중..."
        else:
            # 아직 시작되지 않은 작업
            return "-"


class SocialMediaSourceSerializer(serializers.ModelSerializer):
    """
    소셜 미디어 소스 Serializer

    SocialMediaSource 모델을 JSON으로 변환하거나, JSON으로부터 SocialMediaSource 객체를 생성합니다.

    주요 기능:
    - 소셜 미디어 소스 정보 직렬화/역직렬화
    - 수집된 게시물 개수 표시 (읽기 전용)
    - 플랫폼별 검증
    """

    # 읽기 전용 필드: 수집된 게시물 개수
    post_count = serializers.IntegerField(
        read_only=True, help_text="이 소스에서 수집된 게시물 개수"
    )

    # 읽기 전용 필드: 마지막 수집 시간 (형식화)
    last_collected_at_display = serializers.DateTimeField(
        read_only=True,
        source="last_collected_at",
        format="%Y-%m-%d %H:%M:%S",
        help_text="마지막 수집 시간 (형식화된 문자열)",
    )

    # 플랫폼 표시 이름
    platform_display = serializers.CharField(
        source="get_platform_display",
        read_only=True,
        help_text='플랫폼 표시 이름 (예: "Reddit", "DC Inside")',
    )

    class Meta:
        model = SocialMediaSource
        fields = "__all__"

        read_only_fields = [
            "id",
            "created_at",
            "updated_at",
            "last_collected_at",
        ]

        extra_kwargs = {
            "platform": {
                "help_text": "소셜 미디어 플랫폼 타입 (reddit, dcinside)",
                "required": True,
            },
            "identifier": {
                "help_text": "플랫폼별 식별자 (Reddit: subreddit 이름, DC Inside: 갤러리 이름)",
                "required": True,
            },
            "display_name": {
                "help_text": "소스의 표시용 이름 (예: r/technology, dcbest 갤러리)",
                "required": True,
            },
            "url": {
                "help_text": "RSS 피드 URL 또는 API 엔드포인트 주소",
                "required": True,
            },
            "source_type": {
                "help_text": "데이터 수집 방식 (rss, api, scraping)",
                "required": False,
            },
            "category": {
                "help_text": "소스의 카테고리 또는 태그",
                # 모델에 blank=True, null=True가 있으면 자동 적용
            },
            "is_active": {
                "help_text": "이 소스에서 데이터를 수집할지 여부",
                # 모델에 default=True가 있으면 자동 적용
            },
            "collection_interval": {
                "help_text": "데이터 수집 주기 (분 단위)",
                "min_value": 1,  # 검증용 (모델에는 없음)
                "max_value": 1440,  # 검증용 (모델에는 없음)
            },
            "api_credentials": {
                "help_text": "API 인증에 필요한 정보 (JSON 형태)",
                # 모델에 blank=True, null=True가 있으면 자동 적용
            },
        }

    def validate(self, data: Dict[str, Any]) -> Dict[str, Any]:
        """
        전체 데이터 검증 메서드
        """
        # identifier 필드 검증
        if "identifier" in data:
            identifier = data.get("identifier", "")
            if isinstance(identifier, str):
                identifier = identifier.strip()

            if not identifier:
                raise serializers.ValidationError(
                    {"identifier": "식별자는 필수입니다."}
                )

            data["identifier"] = identifier

        # display_name 필드 검증
        if "display_name" in data:
            display_name = data.get("display_name", "")
            if isinstance(display_name, str):
                display_name = display_name.strip()

            if not display_name:
                raise serializers.ValidationError(
                    {"display_name": "표시 이름은 필수입니다."}
                )

            data["display_name"] = display_name
        else:
            # display_name이 제공되지 않은 경우
            raise serializers.ValidationError(
                {"display_name": "표시 이름은 필수입니다."}
            )

        # url 필드 검증
        if "url" in data:
            url = data.get("url", "")
            if isinstance(url, str):
                url = url.strip()

            if not url:
                raise serializers.ValidationError({"url": "URL은 필수입니다."})

            if not (url.startswith("http://") or url.startswith("https://")):
                raise serializers.ValidationError(
                    {"url": "URL은 http:// 또는 https://로 시작해야 합니다."}
                )

            data["url"] = url

        # platform별 identifier 검증
        if "platform" in data and "identifier" in data:
            platform = data.get("platform")
            identifier = data.get("identifier", "")

            if platform == "reddit":
                # Reddit: subreddit 이름은 소문자, 숫자, 언더스코어만 허용
                if not identifier.replace("_", "").replace("-", "").isalnum():
                    raise serializers.ValidationError(
                        {
                            "identifier": "Reddit subreddit 이름은 영문자, 숫자, 언더스코어, 하이픈만 허용됩니다."
                        }
                    )
            elif platform == "dcinside":
                # DC Inside: 갤러리 이름은 영문자, 숫자, 언더스코어, 하이픈만 허용
                if not identifier.replace("_", "").replace("-", "").isalnum():
                    raise serializers.ValidationError(
                        {
                            "identifier": "DC Inside 갤러리 이름은 영문자, 숫자, 언더스코어, 하이픈만 허용됩니다."
                        }
                    )

        return data

    def to_representation(self, instance):
        """
        직렬화 시 추가 데이터를 포함하는 메서드
        """
        representation = super().to_representation(instance)

        # 수집된 게시물 개수 추가
        representation["post_count"] = instance.posts.count()

        return representation


class BaseSocialMediaPostSerializer(serializers.ModelSerializer):
    """
    소셜 미디어 게시물 기본 Serializer

    공통 필드와 메서드를 정의합니다.
    플랫폼별 시리얼라이저는 이 클래스를 상속받아 사용합니다.
    """

    # 중첩된 소스 정보
    source_detail = SocialMediaSourceSerializer(
        source="source", read_only=True, help_text="소셜 미디어 소스 상세 정보"
    )

    # 소스 이름
    source_name = serializers.SerializerMethodField(
        read_only=True, help_text="소셜 미디어 소스 이름"
    )

    # 플랫폼 정보
    platform = serializers.SerializerMethodField(
        read_only=True, help_text="플랫폼 타입 (소스에서 가져옴)"
    )

    # 제목 요약
    title_short = serializers.SerializerMethodField(
        help_text="제목 요약 (50자로 제한)",
    )

    # 게시 시간 형식화
    published_at_display = serializers.DateTimeField(
        read_only=True,
        source="published_at",
        format="%Y-%m-%d %H:%M:%S",
        help_text="게시 시간 (형식화된 문자열)",
    )

    # 수집 시간 형식화
    collected_at_display = serializers.DateTimeField(
        read_only=True,
        source="collected_at",
        format="%Y-%m-%d %H:%M:%S",
        help_text="수집 시간 (형식화된 문자열)",
    )

    class Meta:
        model = SocialMediaPost
        fields = "__all__"

        read_only_fields = [
            "id",
            "collected_at",
            "url",  # URL은 수집 시 자동 설정
        ]

    def get_source_name(self, obj: SocialMediaPost) -> str:
        """소스 이름 반환"""
        return str(obj.source) if obj.source else "Unknown"

    def get_platform(self, obj: SocialMediaPost) -> Optional[str]:
        """플랫폼 타입 반환"""
        return obj.platform if obj.source else None

    def get_title_short(self, obj: SocialMediaPost) -> str:
        """제목을 50자로 제한하여 반환"""
        if obj.title and len(obj.title) > 50:
            return obj.title[:50] + "..."
        return obj.title or ""

    def to_representation(self, instance):
        """
        썸네일 URL을 프록시 URL로 변환

        DC Inside 등 Referer가 필요한 이미지는 프록시를 통해 제공합니다.
        Reddit 이미지는 원본 URL을 그대로 사용합니다.
        """
        representation = super().to_representation(instance)

        thumbnail_url = representation.get("thumbnail_url")
        if thumbnail_url:
            # DC Inside 이미지는 프록시 URL로 변환
            if (
                "dcinside" in thumbnail_url.lower()
                or "dcimg" in thumbnail_url.lower()
                or "dccdn" in thumbnail_url.lower()
            ):
                from urllib.parse import quote

                # 프록시 URL 생성
                encoded_url = quote(thumbnail_url, safe="")
                request = self.context.get("request")

                if request:
                    base_url = request.build_absolute_uri("/")[
                        :-1
                    ]  # 마지막 슬래시 제거
                    representation["thumbnail_url"] = (
                        f"{base_url}/api/collector/thumbnail-proxy/?url={encoded_url}"
                    )
                else:
                    # request가 없으면 상대 경로 사용
                    representation["thumbnail_url"] = (
                        f"/api/collector/thumbnail-proxy/?url={encoded_url}"
                    )

        return representation


class RedditPostSerializer(BaseSocialMediaPostSerializer):
    """
    Reddit 게시물 Serializer

    Reddit 플랫폼에 특화된 필드와 검증을 포함합니다.
    """

    class Meta(BaseSocialMediaPostSerializer.Meta):
        fields = [
            "id",
            "source",
            "source_detail",
            "source_name",
            "platform",
            "platform_post_id",
            "url",
            "title",
            "title_short",
            "content",
            "original_title",
            "original_content",  # Reddit 전용: 원본 제목/내용
            "author",
            "published_at",
            "published_at_display",
            "collected_at",
            "collected_at_display",
            "likes_count",
            "comments_count",
            "shares_count",
            "views_count",
            "subreddit",
            "thumbnail_url",
            "raw_data",
            "is_processed",
        ]

        extra_kwargs = {
            "source": {
                "help_text": "소셜 미디어 소스 ID",
                "required": True,
            },
            "title": {
                "help_text": "게시물의 제목 (필수)",
                "required": True,
            },
            "content": {
                "help_text": "게시물의 본문 내용 (필수)",
                "required": True,
            },
            "subreddit": {
                "help_text": "Reddit 서브레딧 이름",
            },
        }

    def validate(self, data: Dict[str, Any]) -> Dict[str, Any]:
        """Reddit 게시물 검증"""
        # source 필드 검증
        source = data.get("source")
        if not source:
            if not self.instance:
                raise serializers.ValidationError({"source": "소스는 필수입니다."})
            source = self.instance.source if self.instance else None

        # Reddit 플랫폼 검증
        if source:
            if isinstance(source, int):
                from data_collector.models import SocialMediaSource

                try:
                    source_obj = SocialMediaSource.objects.get(id=source)
                except SocialMediaSource.DoesNotExist:
                    raise serializers.ValidationError(
                        {"source": "존재하지 않는 소스입니다."}
                    )
            else:
                source_obj = source

            if source_obj.platform != "reddit":
                raise serializers.ValidationError(
                    {"source": "Reddit 소스만 사용할 수 있습니다."}
                )

            # title 필수
            title = data.get("title")
            if not title:
                if not (self.instance and self.instance.title):
                    raise serializers.ValidationError(
                        {"title": "Reddit 게시물은 제목(title)이 필수입니다."}
                    )

            # content 필수
            content = data.get("content")
            if not content:
                if not (self.instance and self.instance.content):
                    raise serializers.ValidationError(
                        {"content": "Reddit 게시물은 내용(content)이 필수입니다."}
                    )

        # url 필드 검증
        if "url" in data:
            url = data.get("url", "")
            if url:
                if isinstance(url, str):
                    url = url.strip()
                if not (url.startswith("http://") or url.startswith("https://")):
                    raise serializers.ValidationError(
                        {"url": "URL은 http:// 또는 https://로 시작해야 합니다."}
                    )
                data["url"] = url

        return data


class DCInsidePostSerializer(BaseSocialMediaPostSerializer):
    """
    DC Inside 게시물 Serializer

    DC Inside 플랫폼에 특화된 필드와 검증을 포함합니다.
    """

    class Meta(BaseSocialMediaPostSerializer.Meta):
        fields = [
            "id",
            "source",
            "source_detail",
            "source_name",
            "platform",
            "platform_post_id",
            "url",
            "title",
            "title_short",
            "content",
            "author",
            "published_at",
            "published_at_display",
            "collected_at",
            "collected_at_display",
            "likes_count",
            "comments_count",
            "shares_count",
            "views_count",
            "gall_name",
            "post_num",
            "ip",
            "images",
            "thumbnail_url",
            "raw_data",
            "is_processed",
        ]

        extra_kwargs = {
            "source": {
                "help_text": "소셜 미디어 소스 ID",
                "required": True,
            },
            "title": {
                "help_text": "게시물의 제목 (필수)",
                "required": True,
            },
            "content": {
                "help_text": "게시물의 본문 내용 (필수)",
                "required": True,
            },
            "gall_name": {
                "help_text": "DC Inside 갤러리 이름 (예: dcbest, programming)",
            },
            "post_num": {
                "help_text": "DC Inside 게시글 번호",
            },
            "ip": {
                "help_text": "작성자 IP 주소 (일부만 표시)",
            },
            "images": {
                "help_text": "게시글에 포함된 이미지 URL 목록 (JSON 배열)",
            },
        }

    def to_representation(self, instance):
        """
        DC Inside 썸네일 URL을 프록시 URL로 변환

        부모 클래스의 to_representation을 호출하여 프록시 URL 변환을 보장합니다.
        """
        return super().to_representation(instance)

    def validate(self, data: Dict[str, Any]) -> Dict[str, Any]:
        """DC Inside 게시물 검증"""
        # source 필드 검증
        source = data.get("source")
        if not source:
            if not self.instance:
                raise serializers.ValidationError({"source": "소스는 필수입니다."})
            source = self.instance.source if self.instance else None

        # DC Inside 플랫폼 검증
        if source:
            if isinstance(source, int):
                from data_collector.models import SocialMediaSource

                try:
                    source_obj = SocialMediaSource.objects.get(id=source)
                except SocialMediaSource.DoesNotExist:
                    raise serializers.ValidationError(
                        {"source": "존재하지 않는 소스입니다."}
                    )
            else:
                source_obj = source

            if source_obj.platform != "dcinside":
                raise serializers.ValidationError(
                    {"source": "DC Inside 소스만 사용할 수 있습니다."}
                )

            # title 필수
            title = data.get("title")
            if not title:
                if not (self.instance and self.instance.title):
                    raise serializers.ValidationError(
                        {"title": "DC Inside 게시물은 제목(title)이 필수입니다."}
                    )

            # content 필수
            content = data.get("content")
            if not content:
                if not (self.instance and self.instance.content):
                    raise serializers.ValidationError(
                        {"content": "DC Inside 게시물은 내용(content)이 필수입니다."}
                    )

        # url 필드 검증
        if "url" in data:
            url = data.get("url", "")
            if url:
                if isinstance(url, str):
                    url = url.strip()
                if not (url.startswith("http://") or url.startswith("https://")):
                    raise serializers.ValidationError(
                        {"url": "URL은 http:// 또는 https://로 시작해야 합니다."}
                    )
                data["url"] = url

        return data
