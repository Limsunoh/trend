# 트러블슈팅 가이드

이 문서는 프로젝트 개발 및 운영 중 발생한 문제와 해결 방법을 정리합니다.

## 목차
1. [DC Inside 썸네일 이미지 수집 및 표시 문제](#dc-inside-썸네일-이미지-수집-및-표시-문제)

---

## DC Inside 썸네일 이미지 수집 및 표시 문제

### 문제 상황

1. **썸네일 URL이 NULL로 저장됨**
   - DC Inside 게시글 수집 시 `thumbnail_url` 필드가 NULL로 저장됨
   - Reddit은 정상적으로 썸네일 URL이 저장됨
   - `dcapi.read.post()`로 가져온 `post_data`의 `images` 필드가 비어있음

2. **selenium_title에는 thumbnail 필드 존재**
   - `dcapi.read.title_selenium`으로 가져온 데이터에는 `thumbnail` 필드가 있음
   - 하지만 `dcapi.read.post()`로 가져온 상세 정보에는 썸네일이 없음

3. **403 Forbidden 에러**
   - 썸네일 URL을 추출한 후 브라우저에서 직접 열면 403 에러 발생
   - Reddit 이미지는 정상적으로 표시됨

4. **이미지 다운로드 문제**
   - 프록시 URL을 통해 이미지를 제공했지만, 브라우저에서 이미지가 표시되지 않고 다운로드됨
   - 개발자 도구에서 `content-type: application/octet-stream`으로 확인됨

### 원인 분석

1. **NULL 값 원인**
   - `dcapi.read.post()`가 반환하는 `post_data`의 `images` 필드가 비어있음
   - `content` HTML에서 이미지를 추출하려 했지만 실패
   - `selenium_title`의 `thumbnail` 필드를 사용하지 않았음

2. **403 에러 원인**
   - DC Inside 서버가 `Referer` 헤더를 검증하여 직접 접근을 차단
   - Reddit은 이런 제한이 없어 바로 접근 가능

3. **다운로드 문제 원인**
   - DC Inside 서버가 `Content-Type: application/octet-stream`을 반환
   - 브라우저가 이를 일반 파일로 인식하여 다운로드 처리
   - 실제 이미지 데이터는 정상이지만 Content-Type이 잘못 설정됨

### 해결 방법

#### 1. selenium_title의 thumbnail 필드 우선 사용

**파일**: `data_collector/services.py`

`dcapi.read.post()`로 가져온 데이터에 썸네일이 없을 경우, `selenium_title`에서 가져온 `thumbnail` 필드를 우선 사용:

```python
# 0. selenium_title에서 가져온 thumbnail 우선 사용 (가장 신뢰할 수 있는 소스)
if post_info.get('thumbnail'):
    thumbnail_url = post_info.get('thumbnail')
    self.logger.info(f"게시글 {post_num}: 썸네일 추출 성공 (selenium_title): {thumbnail_url[:150]}")
```

#### 2. content HTML에서 이미지 추출 (백업)

`selenium_title`에도 없을 경우, `post_data['content']` HTML에서 이미지 URL 추출:

```python
# 2. thumbnail_url이 여전히 없으면 content HTML에서 <img src> 추출
if not thumbnail_url:
    content = post_data.get('content', '')
    if content:
        import re
        from html import unescape
        
        # <img src="..." /> 패턴 찾기
        img_pattern = r'<img[^>]+src\s*=\s*["\']?([^"\'>\s]+)["\']?[^>]*>'
        matches = re.findall(img_pattern, content, re.IGNORECASE)
        
        if matches:
            decoded_matches = [unescape(url) for url in matches]
            # 실제 게시글 이미지 필터링 (dcimg, dccdn 도메인만)
            image_domains = ['dcimg', 'dccdn', 'viewimage']
            filtered_matches = [
                url for url in decoded_matches
                if any(domain in url for domain in image_domains)
                and 'nstatic' not in url
                and 'logo' not in url.lower()
            ]
            
            if filtered_matches:
                thumbnail_url = filtered_matches[0]
```

#### 3. 이미지 프록시 엔드포인트 구현

**파일**: `data_collector/views.py`

```python
class ThumbnailProxyView(APIView):
    """
    썸네일 이미지 프록시 뷰
    
    DC Inside 등 Referer 헤더가 필요한 이미지를 프록시를 통해 제공합니다.
    Reddit 이미지는 그대로 리다이렉트합니다.
    """
    permission_classes = [AllowAny]
    
    def get(self, request):
        image_url = request.query_params.get('url')
        # ... (상세 구현)
```

**URL 등록**: `data_collector/urls.py`
```python
urlpatterns = router.urls + [
    path('thumbnail-proxy/', ThumbnailProxyView.as_view(), name='thumbnail-proxy'),
]
```

#### 4. Serializer에서 자동 URL 변환

**파일**: `data_collector/serializers.py`

`BaseSocialMediaPostSerializer`의 `to_representation` 메서드에서:
- DC Inside 이미지 URL을 프록시 URL로 자동 변환
- Reddit 이미지는 원본 URL 유지

```python
def to_representation(self, instance):
    representation = super().to_representation(instance)
    thumbnail_url = representation.get('thumbnail_url')
    
    if thumbnail_url and ('dcinside' in thumbnail_url.lower() or 
                          'dcimg' in thumbnail_url.lower() or 
                          'dccdn' in thumbnail_url.lower()):
        # 프록시 URL로 변환
        encoded_url = quote(thumbnail_url, safe='')
        request = self.context.get('request')
        if request:
            base_url = request.build_absolute_uri('/')[:-1]
            representation['thumbnail_url'] = f"{base_url}/api/collector/thumbnail-proxy/?url={encoded_url}"
    
    return representation
```

**중요**: `DCInsidePostSerializer`의 `Meta.fields`에 `'thumbnail_url'`이 포함되어 있어야 함

#### 5. Content-Type 자동 감지 (매직 넘버 사용)

**파일**: `data_collector/views.py`

서버가 반환한 Content-Type이 `application/octet-stream`인 경우, 실제 이미지 데이터의 매직 넘버로 타입을 감지:

```python
# 이미지 파일 시그니처(매직 넘버)로 감지
if len(image_data) >= 4:
    # JPEG: FF D8 FF
    if image_data[:3] == b'\xff\xd8\xff':
        content_type = 'image/jpeg'
    # PNG: 89 50 4E 47
    elif image_data[:4] == b'\x89PNG':
        content_type = 'image/png'
    # GIF: 47 49 46 38 (GIF8)
    elif image_data[:4] == b'GIF8':
        content_type = 'image/gif'
    # WebP: RIFF...WEBP
    elif len(image_data) >= 12 and image_data[:4] == b'RIFF' and image_data[8:12] == b'WEBP':
        content_type = 'image/webp'
```

#### 6. 응답 헤더 설정

```python
http_response = HttpResponse(image_data, content_type=content_type)
http_response['Content-Disposition'] = 'inline; filename="thumbnail.jpg"'
http_response['Cache-Control'] = 'public, max-age=3600'
http_response['Access-Control-Allow-Origin'] = '*'
http_response['X-Content-Type-Options'] = 'nosniff'
```

### 해결 과정 요약

1. **NULL 값 문제 해결**
   - `selenium_title`의 `thumbnail` 필드를 우선 사용
   - 없으면 `content` HTML에서 이미지 URL 추출
   - `DCInsidePostSerializer`의 `Meta.fields`에 `'thumbnail_url'` 추가

2. **403 에러 해결**
   - 이미지 프록시 엔드포인트 구현
   - `Referer` 헤더를 포함하여 DC Inside 서버에서 이미지 가져오기
   - Serializer에서 자동으로 프록시 URL로 변환

3. **다운로드 문제 해결**
   - 매직 넘버로 실제 이미지 타입 감지
   - `Content-Type`을 올바르게 설정 (`image/jpeg`, `image/png` 등)
   - `Content-Disposition: inline` 설정

### 핵심 포인트

1. **썸네일 추출 우선순위**
   - 1순위: `selenium_title`의 `thumbnail` 필드
   - 2순위: `post_data['images']` 리스트
   - 3순위: `post_data['content']` HTML에서 추출

2. **DB에는 원본 URL 저장**: DB/Admin에서는 원본 URL이 보이는 것이 정상
3. **API 응답에서만 프록시 URL 변환**: Serializer의 `to_representation`에서 변환
4. **매직 넘버로 Content-Type 감지**: 서버 응답의 Content-Type이 잘못된 경우 실제 데이터로 판단
5. **Content-Disposition: inline**: 브라우저에서 직접 표시되도록 설정

### 테스트 방법

1. API 호출: `/api/collector/social/?platform=dcinside`
2. 응답의 `thumbnail_url`이 프록시 URL인지 확인
3. 프록시 URL을 브라우저에서 열어 이미지가 표시되는지 확인
4. 개발자 도구에서 `content-type: image/jpeg` (또는 다른 이미지 타입) 확인

### 참고 사항

- 브라우저 캐시 때문에 이전 응답이 보일 수 있으니 하드 리프레시(Ctrl+F5) 권장
- 프록시를 통해 이미지를 제공하므로 서버 부하가 증가할 수 있음
- 필요시 CDN이나 별도 이미지 서버 사용 고려

