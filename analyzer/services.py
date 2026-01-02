"""
형태소 분석 서비스 모듈

PyKOMORAN을 사용한 한국어 형태소 분석 기능을 제공합니다.
"""
import logging
import os
from typing import List, Dict, Optional, Tuple
from collections import Counter
from datetime import timedelta
from django.utils import timezone

logger = logging.getLogger(__name__)

try:
    from PyKomoran import Komoran
    PYKOMORAN_AVAILABLE = True
except ImportError:
    PYKOMORAN_AVAILABLE = False
    logger.warning("PyKomoran이 설치되지 않았습니다. pip install PyKomoran을 실행하세요.")

# 불용어 리스트 캐시 (한 번만 로드)
_STOPWORDS_CACHE: Optional[set] = None
_STOPWORDS_FILE_MTIME: Optional[float] = None  # 파일 수정 시간


class MorphologicalAnalyzer:
    """
    PyKOMORAN을 사용한 형태소 분석기
    
    한국어 텍스트를 형태소로 분석하고, 명사 등 특정 품사를 추출합니다.
    """
    
    def __init__(self, model_type: str = "STABLE", java_path: Optional[str] = None):
        """
        형태소 분석기 초기화
        
        Args:
            model_type: KOMORAN 모델 타입 ("STABLE" 또는 "EXP")
                - STABLE: 안정적인 모델 (기본값)
                - EXP: 실험적 모델 (더 정확하지만 느릴 수 있음)
            java_path: Java 실행 파일 경로 (선택사항)
                - Java가 PATH에 없을 때만 지정
                - 예: "C:\\Program Files\\Java\\jdk-11\\bin\\java.exe"
        """
        if not PYKOMORAN_AVAILABLE:
            raise ImportError(
                "PyKomoran이 설치되지 않았습니다. "
                "다음 명령어로 설치하세요: pip install PyKomoran"
            )
        
        # Java 경로 설정 (필요한 경우)
        if java_path and os.path.exists(java_path):
            os.environ['JAVA_HOME'] = os.path.dirname(os.path.dirname(java_path))
            logger.info(f"Java 경로 설정: {java_path}")
        elif java_path:
            logger.warning(f"지정한 Java 경로가 존재하지 않습니다: {java_path}")
        
        try:
            self.komoran = Komoran(model_type)
            self.model_type = model_type
            logger.info(f"PyKOMORAN 형태소 분석기 초기화 완료 (모델: {model_type})")
        except Exception as e:
            error_msg = str(e)
            if "WinError 2" in error_msg or "파일을 찾을 수 없습니다" in error_msg:
                logger.error(
                    "Java를 찾을 수 없습니다. Java가 설치되어 있는지 확인하세요.\n"
                    "Java 설치 확인: java -version\n"
                    "또는 java_path 파라미터로 Java 경로를 지정하세요."
                )
            else:
                logger.error(f"PyKOMORAN 초기화 실패: {error_msg}")
            raise
    
    def analyze(self, text: str) -> List[Tuple[str, str]]:
        """
        텍스트를 형태소 분석
        
        Args:
            text: 분석할 텍스트
            
        Returns:
            형태소와 품사의 튜플 리스트
            예: [('대한민국', 'NNP'), ('은', 'JX'), ('민주', 'NNP'), ...]
        """
        if not text or not text.strip():
            return []
        
        try:
            # PyKOMORAN 분석 결과를 파싱
            result = self.komoran.get_plain_text(text)
            
            # 결과 파싱: "형태소/품사 형태소/품사 ..." 형식
            morphemes = []
            for item in result.split():
                if '/' in item:
                    morph, pos = item.rsplit('/', 1)
                    morphemes.append((morph, pos))
            
            return morphemes
        except Exception as e:
            logger.error(f"형태소 분석 실패 (텍스트: {text[:50]}...): {str(e)}")
            return []
    
    def extract_nouns(self, text: str) -> List[str]:
        """
        텍스트에서 명사만 추출
        
        Args:
            text: 분석할 텍스트
            
        Returns:
            명사 리스트
        """
        morphemes = self.analyze(text)
        
        # 명사 품사 태그 (KOMORAN 기준)
        # NNP: 고유명사, NNG: 일반명사, NNB: 의존명사 등
        noun_tags = ['NNP', 'NNG', 'NNB', 'NNBC']
        
        nouns = [morph for morph, pos in morphemes if pos in noun_tags]
        return nouns
    
    def extract_keywords(
        self, 
        text: str, 
        min_length: int = 2,
        exclude_stopwords: bool = True
    ) -> List[str]:
        """
        텍스트에서 키워드(명사) 추출
        
        Args:
            text: 분석할 텍스트
            min_length: 최소 글자 수 (기본값: 2)
            exclude_stopwords: 불용어 제거 여부 (기본값: True)
            
        Returns:
            키워드 리스트
        """
        nouns = self.extract_nouns(text)
        
        # 최소 길이 필터링
        keywords = [noun for noun in nouns if len(noun) >= min_length]
        
        # 불용어 제거
        if exclude_stopwords:
            keywords = self._remove_stopwords(keywords)
        
        return keywords
    
    def _load_stopwords(self) -> set:
        """
        stopwords_ko.txt 파일에서 불용어 리스트 로드
        
        파일이 수정되었으면 캐시를 무효화하고 다시 로드합니다.
        
        Returns:
            불용어 집합
        """
        global _STOPWORDS_CACHE, _STOPWORDS_FILE_MTIME
        
        # 파일 경로 설정
        stopwords_file = os.path.join(
            os.path.dirname(__file__),
            'data',
            'stopwords_ko.txt'
        )
        
        # 파일 수정 시간 확인
        file_mtime = None
        if os.path.exists(stopwords_file):
            file_mtime = os.path.getmtime(stopwords_file)
        
        # 캐시가 있고 파일이 변경되지 않았으면 재사용
        if (_STOPWORDS_CACHE is not None and 
            _STOPWORDS_FILE_MTIME is not None and
            file_mtime == _STOPWORDS_FILE_MTIME):
            return _STOPWORDS_CACHE
        
        # 캐시 무효화 또는 새로 로드
        stopwords = set()
        
        # 파일에서 불용어 로드
        if os.path.exists(stopwords_file):
            try:
                with open(stopwords_file, 'r', encoding='utf-8') as f:
                    content = f.read()
                    # 줄바꿈 문자로 분리 (여러 형식 지원)
                    # \r\n (Windows), \n (Unix), \r (Mac) 모두 처리
                    lines = content.replace('\r\n', '\n').replace('\r', '\n').split('\n')
                    
                    for line in lines:
                        word = line.strip()
                        if word:  # 빈 줄 제외
                            stopwords.add(word)
                    
                logger.info(
                    f"불용어 파일 로드 완료: {len(stopwords)}개 단어 "
                    f"({stopwords_file})"
                )
            except Exception as e:
                logger.error(
                    f"불용어 파일 로드 실패: {str(e)}", exc_info=True
                )
                # 기본 불용어로 폴백
                stopwords = self._get_default_stopwords()
        else:
            logger.warning(
                f"불용어 파일을 찾을 수 없습니다: {stopwords_file}\n"
                "기본 불용어 리스트를 사용합니다."
            )
            # 기본 불용어로 폴백
            stopwords = self._get_default_stopwords()
        
        # 캐시에 저장
        _STOPWORDS_CACHE = stopwords
        _STOPWORDS_FILE_MTIME = file_mtime
        return stopwords
    
    def _get_default_stopwords(self) -> set:
        """
        기본 불용어 리스트 (파일이 없을 때 사용)
        
        Returns:
            기본 불용어 집합
        """
        return {
            '것', '수', '등', '때', '곳', '년', '월', '일', '시', '분',
            '이', '가', '을', '를', '의', '에', '와', '과', '도', '로',
            '것이', '것을', '것에', '것으로', '것도',
            '그', '그것', '그런', '그렇게',
            '이것', '저것', '이런', '저런',
            '때문', '위해', '통해', '대해',
        }
    
    def _remove_stopwords(self, words: List[str]) -> List[str]:
        """
        불용어 제거
        
        Args:
            words: 단어 리스트
            
        Returns:
            불용어가 제거된 단어 리스트
        """
        stopwords = self._load_stopwords()
        return [word for word in words if word not in stopwords]
    
    def get_keyword_frequency(
        self, 
        texts: List[str],
        min_length: int = 2,
        exclude_stopwords: bool = True
    ) -> Dict[str, int]:
        """
        여러 텍스트에서 키워드 빈도 계산
        
        Args:
            texts: 텍스트 리스트
            min_length: 최소 글자 수
            exclude_stopwords: 불용어 제거 여부
            
        Returns:
            키워드와 빈도의 딕셔너리 (절대 빈도)
        """
        all_keywords = []
        
        for text in texts:
            if text:
                keywords = self.extract_keywords(
                    text, 
                    min_length=min_length,
                    exclude_stopwords=exclude_stopwords
                )
                all_keywords.extend(keywords)
        
        # 빈도 계산
        frequency = Counter(all_keywords)
        
        return dict(frequency)
    
    def normalize_frequency(
        self,
        frequency: Dict[str, int]
    ) -> Dict[str, float]:
        """
        키워드 빈도를 상대 빈도로 정규화
        
        플랫폼별 데이터 규모 차이를 보정하기 위해 상대 빈도로 변환합니다.
        상대 빈도 = 절대 빈도 / 전체 단어 수
        
        Args:
            frequency: 키워드와 절대 빈도의 딕셔너리
        
        Returns:
            키워드와 상대 빈도의 딕셔너리 (0.0 ~ 1.0 범위)
        """
        if not frequency:
            return {}
        
        # 상대 빈도: 절대 빈도 / 전체 단어 수
        total = sum(frequency.values())
        if total == 0:
            return {}
        
        return {word: count / total for word, count in frequency.items()}
    
    def get_normalized_keyword_frequency(
        self,
        texts: List[str],
        min_length: int = 2,
        exclude_stopwords: bool = True
    ) -> Dict[str, float]:
        """
        여러 텍스트에서 키워드 빈도를 계산하고 상대 빈도로 정규화
        
        Args:
            texts: 텍스트 리스트
            min_length: 최소 글자 수
            exclude_stopwords: 불용어 제거 여부
            
        Returns:
            키워드와 상대 빈도의 딕셔너리 (0.0 ~ 1.0 범위)
        """
        # 절대 빈도 계산
        absolute_frequency = self.get_keyword_frequency(
            texts, min_length, exclude_stopwords
        )
        
        # 상대 빈도로 정규화
        normalized_frequency = self.normalize_frequency(absolute_frequency)
        
        return normalized_frequency


# 싱글톤 인스턴스 (전역에서 재사용)
_analyzer_instance: Optional[MorphologicalAnalyzer] = None


def clear_stopwords_cache():
    """
    불용어 캐시 초기화
    
    파일을 수정한 후 즉시 반영하고 싶을 때 사용합니다.
    """
    global _STOPWORDS_CACHE, _STOPWORDS_FILE_MTIME
    _STOPWORDS_CACHE = None
    _STOPWORDS_FILE_MTIME = None
    logger.info("불용어 캐시가 초기화되었습니다.")


def get_analyzer(model_type: str = "STABLE", java_path: Optional[str] = None) -> MorphologicalAnalyzer:
    """
    형태소 분석기 싱글톤 인스턴스 반환

    Args:
        model_type: KOMORAN 모델 타입 ("STABLE" 또는 "EXP")
        java_path: Java 실행 파일 경로 (선택사항)

    Returns:
        MorphologicalAnalyzer 인스턴스
    """
    global _analyzer_instance

    if (_analyzer_instance is None or
            _analyzer_instance.model_type != model_type):
        _analyzer_instance = MorphologicalAnalyzer(
            model_type=model_type,
            java_path=java_path
        )

    return _analyzer_instance


# ============================================================================
# DB 데이터 분석 함수들
# ============================================================================

def extract_text_from_news_article(article) -> str:
    """
    NewsArticle 객체에서 분석할 텍스트 추출
    
    Args:
        article: NewsArticle 모델 인스턴스
        
    Returns:
        분석할 텍스트 (title + description)
    """
    text = article.title or ""
    if article.description:
        text += " " + article.description
    return text.strip()


def extract_text_from_sns_post(post) -> str:
    """
    SocialMediaPost 객체에서 분석할 텍스트 추출
    
    Args:
        post: SocialMediaPost 모델 인스턴스
        
    Returns:
        분석할 텍스트 (title + content)
    """
    text = post.title or ""
    if post.content:
        text += " " + post.content
    return text.strip()


def analyze_news_articles(
    queryset=None,
    days: int = 7,
    min_length: int = 2,
    exclude_stopwords: bool = True,
    top_n: Optional[int] = None
) -> Dict[str, any]:
    """
    뉴스 기사에서 키워드를 추출하고 정규화된 빈도를 계산합니다.
    
    이 함수는:
    1. DB에서 뉴스 기사를 가져옵니다 (또는 제공된 queryset 사용)
    2. 각 기사의 title + description을 텍스트로 추출합니다
    3. 형태소 분석을 통해 키워드를 추출합니다
    4. 절대 빈도를 계산합니다
    5. 상대 빈도로 정규화합니다
    
    Args:
        queryset: NewsArticle QuerySet (None이면 최근 N일간 자동 조회)
        days: 최근 며칠간의 데이터를 분석할지 (queryset이 None일 때만 사용)
        min_length: 최소 글자 수 (기본값: 2)
        exclude_stopwords: 불용어 제거 여부 (기본값: True)
        top_n: 상위 N개 키워드만 반환 (None이면 전체)
        
    Returns:
        분석 결과 딕셔너리:
        {
            'total_articles': 분석한 기사 수,
            'total_keywords': 추출된 키워드 종류 수,
            'absolute_frequency': 절대 빈도 딕셔너리,
            'normalized_frequency': 상대 빈도 딕셔너리 (0.0~1.0),
            'top_keywords': 상위 키워드 리스트 (top_n 지정 시)
        }
        
    사용 예시:
        # 최근 7일간의 뉴스 분석
        result = analyze_news_articles(days=7)
        
        # 특정 queryset 분석
        from data_collector.models import NewsArticle
        articles = NewsArticle.objects.filter(category='정치')
        result = analyze_news_articles(queryset=articles)
        
        # 상위 10개 키워드만
        result = analyze_news_articles(days=7, top_n=10)
    """
    from data_collector.models import NewsArticle
    
    # QuerySet 준비
    if queryset is None:
        start_date = timezone.now() - timedelta(days=days)
        queryset = NewsArticle.objects.filter(
            published_at__gte=start_date
        )
    
    # 텍스트 추출
    texts = []
    for article in queryset:
        text = extract_text_from_news_article(article)
        if text:  # 빈 텍스트 제외
            texts.append(text)
    
    if not texts:
        logger.warning("분석할 뉴스 기사가 없습니다.")
        return {
            'total_articles': 0,
            'total_keywords': 0,
            'absolute_frequency': {},
            'normalized_frequency': {},
            'top_keywords': []
        }
    
    # 분석기 가져오기
    analyzer = get_analyzer()
    
    # 절대 빈도 계산
    absolute_freq = analyzer.get_keyword_frequency(
        texts, min_length=min_length, exclude_stopwords=exclude_stopwords
    )
    
    # 정규화 (상대 빈도)
    normalized_freq = analyzer.normalize_frequency(absolute_freq)
    
    # 상위 키워드 추출 (top_n 지정 시)
    top_keywords = []
    if top_n and top_n > 0:
        sorted_keywords = sorted(
            normalized_freq.items(),
            key=lambda x: x[1],
            reverse=True
        )[:top_n]
        top_keywords = [
            {'keyword': word, 'frequency': freq}
            for word, freq in sorted_keywords
        ]
    
    logger.info(
        f"뉴스 기사 분석 완료: {len(texts)}개 기사, "
        f"{len(absolute_freq)}개 키워드"
    )
    
    return {
        'total_articles': len(texts),
        'total_keywords': len(absolute_freq),
        'absolute_frequency': absolute_freq,
        'normalized_frequency': normalized_freq,
        'top_keywords': top_keywords
    }


def analyze_sns_posts(
    queryset=None,
    days: int = 7,
    min_length: int = 2,
    exclude_stopwords: bool = True,
    top_n: Optional[int] = None
) -> Dict[str, any]:
    """
    소셜 미디어 게시물에서 키워드를 추출하고 정규화된 빈도를 계산합니다.
    
    이 함수는:
    1. DB에서 SNS 게시물을 가져옵니다 (또는 제공된 queryset 사용)
    2. 각 게시물의 title + content를 텍스트로 추출합니다
    3. 형태소 분석을 통해 키워드를 추출합니다
    4. 절대 빈도를 계산합니다
    5. 상대 빈도로 정규화합니다
    
    Args:
        queryset: SocialMediaPost QuerySet (None이면 최근 N일간 자동 조회)
        days: 최근 며칠간의 데이터를 분석할지 (queryset이 None일 때만 사용)
        min_length: 최소 글자 수 (기본값: 2)
        exclude_stopwords: 불용어 제거 여부 (기본값: True)
        top_n: 상위 N개 키워드만 반환 (None이면 전체)
        
    Returns:
        분석 결과 딕셔너리:
        {
            'total_posts': 분석한 게시물 수,
            'total_keywords': 추출된 키워드 종류 수,
            'absolute_frequency': 절대 빈도 딕셔너리,
            'normalized_frequency': 상대 빈도 딕셔너리 (0.0~1.0),
            'top_keywords': 상위 키워드 리스트 (top_n 지정 시)
        }
        
    사용 예시:
        # 최근 7일간의 SNS 게시물 분석
        result = analyze_sns_posts(days=7)
        
        # 특정 플랫폼만 분석
        from data_collector.models import SocialMediaPost
        posts = SocialMediaPost.objects.filter(source__platform='reddit')
        result = analyze_sns_posts(queryset=posts)
    """
    from data_collector.models import SocialMediaPost
    
    # QuerySet 준비
    if queryset is None:
        start_date = timezone.now() - timedelta(days=days)
        queryset = SocialMediaPost.objects.filter(
            published_at__gte=start_date
        )
    
    # 텍스트 추출
    texts = []
    for post in queryset:
        text = extract_text_from_sns_post(post)
        if text:  # 빈 텍스트 제외
            texts.append(text)
    
    if not texts:
        logger.warning("분석할 SNS 게시물이 없습니다.")
        return {
            'total_posts': 0,
            'total_keywords': 0,
            'absolute_frequency': {},
            'normalized_frequency': {},
            'top_keywords': []
        }
    
    # 분석기 가져오기
    analyzer = get_analyzer()
    
    # 절대 빈도 계산
    absolute_freq = analyzer.get_keyword_frequency(
        texts, min_length=min_length, exclude_stopwords=exclude_stopwords
    )
    
    # 정규화 (상대 빈도)
    normalized_freq = analyzer.normalize_frequency(absolute_freq)
    
    # 상위 키워드 추출 (top_n 지정 시)
    top_keywords = []
    if top_n and top_n > 0:
        sorted_keywords = sorted(
            normalized_freq.items(),
            key=lambda x: x[1],
            reverse=True
        )[:top_n]
        top_keywords = [
            {'keyword': word, 'frequency': freq}
            for word, freq in sorted_keywords
        ]
    
    logger.info(
        f"SNS 게시물 분석 완료: {len(texts)}개 게시물, "
        f"{len(absolute_freq)}개 키워드"
    )
    
    return {
        'total_posts': len(texts),
        'total_keywords': len(absolute_freq),
        'absolute_frequency': absolute_freq,
        'normalized_frequency': normalized_freq,
        'top_keywords': top_keywords
    }


def compare_platforms(
    news_queryset=None,
    sns_queryset=None,
    days: int = 7,
    min_length: int = 2,
    exclude_stopwords: bool = True,
    min_frequency: float = 0.001,  # 최소 상대 빈도 (0.1%)
    top_n: Optional[int] = None
) -> Dict[str, any]:
    """
    뉴스와 SNS 플랫폼의 키워드를 비교 분석합니다.
    
    이 함수는:
    1. 뉴스와 SNS 각각에서 키워드를 추출하고 정규화합니다
    2. 공통 키워드를 찾습니다
    3. 플랫폼별 빈도를 비교합니다
    4. 뉴스에만 있는 키워드, SNS에만 있는 키워드를 구분합니다
    
    Args:
        news_queryset: NewsArticle QuerySet (None이면 최근 N일간 자동 조회)
        sns_queryset: SocialMediaPost QuerySet (None이면 최근 N일간 자동 조회)
        days: 최근 며칠간의 데이터를 분석할지
        min_length: 최소 글자 수
        exclude_stopwords: 불용어 제거 여부
        min_frequency: 최소 상대 빈도 (이 값보다 작은 키워드는 제외)
        top_n: 상위 N개 공통 키워드만 반환 (None이면 전체)
        
    Returns:
        비교 분석 결과 딕셔너리:
        {
            'news': 뉴스 분석 결과,
            'sns': SNS 분석 결과,
            'common_keywords': 공통 키워드 비교 리스트,
            'news_only': 뉴스에만 있는 키워드,
            'sns_only': SNS에만 있는 키워드,
            'summary': 요약 통계
        }
        
    사용 예시:
        # 최근 7일간 비교
        result = compare_platforms(days=7)
        
        # 상위 20개 공통 키워드만
        result = compare_platforms(days=7, top_n=20)
        
        # 최소 빈도 필터링
        result = compare_platforms(days=7, min_frequency=0.01)  # 1% 이상만
    """
    # 각 플랫폼 분석
    news_result = analyze_news_articles(
        queryset=news_queryset,
        days=days,
        min_length=min_length,
        exclude_stopwords=exclude_stopwords
    )
    
    sns_result = analyze_sns_posts(
        queryset=sns_queryset,
        days=days,
        min_length=min_length,
        exclude_stopwords=exclude_stopwords
    )
    
    news_norm = news_result['normalized_frequency']
    sns_norm = sns_result['normalized_frequency']
    
    # 최소 빈도 필터링
    news_norm_filtered = {
        k: v for k, v in news_norm.items()
        if v >= min_frequency
    }
    sns_norm_filtered = {
        k: v for k, v in sns_norm.items()
        if v >= min_frequency
    }
    
    # 공통 키워드 찾기
    common_keywords_set = set(news_norm_filtered.keys()) & set(sns_norm_filtered.keys())
    
    # 공통 키워드 비교 리스트 생성
    common_keywords = []
    for keyword in common_keywords_set:
        news_freq = news_norm_filtered[keyword]
        sns_freq = sns_norm_filtered[keyword]
        
        # 차이 계산 (SNS가 더 높으면 양수, 뉴스가 더 높으면 음수)
        diff = sns_freq - news_freq
        
        common_keywords.append({
            'keyword': keyword,
            'news_frequency': news_freq,
            'sns_frequency': sns_freq,
            'difference': diff,
            'news_absolute': news_result['absolute_frequency'].get(keyword, 0),
            'sns_absolute': sns_result['absolute_frequency'].get(keyword, 0)
        })
    
    # 빈도 합으로 정렬 (높은 순)
    common_keywords.sort(
        key=lambda x: x['news_frequency'] + x['sns_frequency'],
        reverse=True
    )
    
    # top_n 적용
    if top_n and top_n > 0:
        common_keywords = common_keywords[:top_n]
    
    # 뉴스에만 있는 키워드
    news_only = {
        k: v for k, v in news_norm_filtered.items()
        if k not in sns_norm_filtered
    }
    
    # SNS에만 있는 키워드
    sns_only = {
        k: v for k, v in sns_norm_filtered.items()
        if k not in news_norm_filtered
    }
    
    # 요약 통계
    summary = {
        'total_news_articles': news_result['total_articles'],
        'total_sns_posts': sns_result['total_posts'],
        'news_keywords_count': len(news_norm_filtered),
        'sns_keywords_count': len(sns_norm_filtered),
        'common_keywords_count': len(common_keywords),
        'news_only_count': len(news_only),
        'sns_only_count': len(sns_only)
    }
    
    logger.info(
        f"플랫폼 비교 분석 완료: "
        f"뉴스 {summary['total_news_articles']}개, "
        f"SNS {summary['total_sns_posts']}개, "
        f"공통 키워드 {summary['common_keywords_count']}개"
    )
    
    return {
        'news': news_result,
        'sns': sns_result,
        'common_keywords': common_keywords,
        'news_only': news_only,
        'sns_only': sns_only,
        'summary': summary
    }


def get_keyword_occurrence_times(
    keyword: str,
    platform: str,  # 'news' or 'sns'
    days: int = 7,
    queryset=None
) -> Dict[str, Optional]:
    """
    특정 키워드가 특정 플랫폼에서 등장한 시간 정보를 추출합니다.
    
    Args:
        keyword: 찾을 키워드
        platform: 'news' 또는 'sns'
        days: 최근 며칠간의 데이터를 검색할지
        queryset: 특정 QuerySet 사용 (None이면 자동 조회)
        
    Returns:
        {
            'first_occurrence': 최초 등장 시간 (datetime 또는 None),
            'last_occurrence': 최종 등장 시간 (datetime 또는 None),
            'occurrence_count': 등장 횟수,
            'all_times': 등장한 모든 시간 리스트 (선택적)
        }
    """
    from data_collector.models import NewsArticle, SocialMediaPost
    
    if platform == 'news':
        Model = NewsArticle
        text_extractor = extract_text_from_news_article
    elif platform == 'sns':
        Model = SocialMediaPost
        text_extractor = extract_text_from_sns_post
    else:
        raise ValueError("platform은 'news' 또는 'sns'여야 합니다.")
    
    # QuerySet 준비
    if queryset is None:
        start_date = timezone.now() - timedelta(days=days)
        queryset = Model.objects.filter(
            published_at__gte=start_date
        ).exclude(published_at__isnull=True).order_by('published_at')
    else:
        queryset = queryset.exclude(published_at__isnull=True).order_by('published_at')
    
    # 분석기 가져오기
    analyzer = get_analyzer()
    
    # 키워드가 포함된 항목 찾기
    occurrence_times = []
    
    for item in queryset:
        text = text_extractor(item)
        if not text:
            continue
        
        # 키워드 추출
        keywords = analyzer.extract_keywords(text, min_length=2, exclude_stopwords=True)
        
        # 키워드가 포함되어 있는지 확인
        if keyword in keywords:
            if item.published_at:
                occurrence_times.append(item.published_at)
    
    if not occurrence_times:
        return {
            'first_occurrence': None,
            'last_occurrence': None,
            'occurrence_count': 0,
            'all_times': []
        }
    
    occurrence_times.sort()  # 시간순 정렬
    
    return {
        'first_occurrence': occurrence_times[0],
        'last_occurrence': occurrence_times[-1],
        'occurrence_count': len(occurrence_times),
        'all_times': occurrence_times
    }


def analyze_time_lag(
    keywords: Optional[List[str]] = None,
    days: int = 7,
    min_frequency: float = 0.001,
    top_n: Optional[int] = None,
    news_queryset=None,
    sns_queryset=None
) -> Dict[str, any]:
    """
    뉴스와 SNS 간의 키워드 전파 패턴을 분석합니다 (시간차 분석).
    
    각 키워드에 대해:
    1. 뉴스와 SNS에서 최초 등장 시간을 찾습니다
    2. 시간차를 계산합니다
    3. 전파 방향을 판단합니다 (뉴스 → SNS 또는 SNS → 뉴스)
    4. 통계를 집계합니다
    
    Args:
        keywords: 분석할 키워드 리스트 (None이면 compare_platforms로 공통 키워드 추출)
        days: 최근 며칠간의 데이터를 분석할지
        min_frequency: 최소 상대 빈도 (키워드 추출 시 사용)
        top_n: 상위 N개 키워드만 분석 (None이면 전체)
        news_queryset: 뉴스 QuerySet (선택적)
        sns_queryset: SNS QuerySet (선택적)
        
    Returns:
        {
            'keywords': 키워드별 분석 결과 리스트,
            'statistics': 통계 정보,
            'timeline_data': 타임라인 시각화용 데이터 (선택적)
        }
    """
    # 키워드 리스트 준비
    if keywords is None:
        # compare_platforms로 공통 키워드 추출
        comparison_result = compare_platforms(
            news_queryset=news_queryset,
            sns_queryset=sns_queryset,
            days=days,
            min_frequency=min_frequency,
            top_n=top_n
        )
        keywords = [item['keyword'] for item in comparison_result['common_keywords']]
    
    if not keywords:
        logger.warning("분석할 키워드가 없습니다.")
        return {
            'keywords': [],
            'statistics': {
                'total_keywords': 0,
                'news_to_sns': 0,
                'sns_to_news': 0,
                'simultaneous': 0,
                'news_only': 0,
                'sns_only': 0,
                'avg_time_lag_news_to_sns': None,
                'avg_time_lag_sns_to_news': None
            }
        }
    
    # 각 키워드에 대해 시간차 분석
    keyword_results = []
    news_to_sns_lags = []  # 뉴스 → SNS 전파 시간차
    sns_to_news_lags = []  # SNS → 뉴스 전파 시간차
    
    for keyword in keywords:
        # 뉴스에서 등장 시간 추출
        news_times = get_keyword_occurrence_times(
            keyword, 'news', days, news_queryset
        )
        news_first = news_times['first_occurrence']
        
        # SNS에서 등장 시간 추출
        sns_times = get_keyword_occurrence_times(
            keyword, 'sns', days, sns_queryset
        )
        sns_first = sns_times['first_occurrence']
        
        # 시간차 계산
        result = {
            'keyword': keyword,
            'news_first_occurrence': news_first,
            'sns_first_occurrence': sns_first,
            'news_occurrence_count': news_times['occurrence_count'],
            'sns_occurrence_count': sns_times['occurrence_count'],
            'direction': None,
            'time_lag_hours': None,
            'time_lag_timedelta': None
        }
        
        if news_first and sns_first:
            # 두 플랫폼 모두에서 등장
            if news_first < sns_first:
                # 뉴스가 먼저
                time_lag = sns_first - news_first
                result['direction'] = 'news_to_sns'
                result['time_lag_timedelta'] = time_lag
                result['time_lag_hours'] = time_lag.total_seconds() / 3600
                news_to_sns_lags.append(time_lag.total_seconds() / 3600)
            elif sns_first < news_first:
                # SNS가 먼저
                time_lag = news_first - sns_first
                result['direction'] = 'sns_to_news'
                result['time_lag_timedelta'] = time_lag
                result['time_lag_hours'] = time_lag.total_seconds() / 3600
                sns_to_news_lags.append(time_lag.total_seconds() / 3600)
            else:
                # 동시 등장 (거의 불가능하지만)
                result['direction'] = 'simultaneous'
                result['time_lag_hours'] = 0
        elif news_first and not sns_first:
            result['direction'] = 'news_only'
        elif sns_first and not news_first:
            result['direction'] = 'sns_only'
        else:
            result['direction'] = 'not_found'
        
        keyword_results.append(result)
    
    # 통계 집계
    news_to_sns_count = sum(1 for r in keyword_results if r['direction'] == 'news_to_sns')
    sns_to_news_count = sum(1 for r in keyword_results if r['direction'] == 'sns_to_news')
    simultaneous_count = sum(1 for r in keyword_results if r['direction'] == 'simultaneous')
    news_only_count = sum(1 for r in keyword_results if r['direction'] == 'news_only')
    sns_only_count = sum(1 for r in keyword_results if r['direction'] == 'sns_only')
    
    # 평균 시간차 계산
    avg_news_to_sns = sum(news_to_sns_lags) / len(news_to_sns_lags) if news_to_sns_lags else None
    avg_sns_to_news = sum(sns_to_news_lags) / len(sns_to_news_lags) if sns_to_news_lags else None
    
    statistics = {
        'total_keywords': len(keyword_results),
        'news_to_sns': news_to_sns_count,
        'sns_to_news': sns_to_news_count,
        'simultaneous': simultaneous_count,
        'news_only': news_only_count,
        'sns_only': sns_only_count,
        'avg_time_lag_news_to_sns_hours': avg_news_to_sns,
        'avg_time_lag_sns_to_news_hours': avg_sns_to_news,
        'news_to_sns_percentage': (news_to_sns_count / len(keyword_results) * 100) if keyword_results else 0,
        'sns_to_news_percentage': (sns_to_news_count / len(keyword_results) * 100) if keyword_results else 0
    }
    
    logger.info(
        f"시간차 분석 완료: {len(keyword_results)}개 키워드, "
        f"뉴스→SNS {news_to_sns_count}개, SNS→뉴스 {sns_to_news_count}개"
    )
    
    return {
        'keywords': keyword_results,
        'statistics': statistics
    }


def get_multiple_keywords_timeline(
    keywords: List[str],
    days: int = 7,
    interval_hours: int = 6,
    news_queryset=None,
    sns_queryset=None
) -> Dict[str, any]:
    """
    여러 키워드의 타임라인 데이터를 한 번에 생성합니다.
    
    Args:
        keywords: 분석할 키워드 리스트
        days: 최근 며칠간의 데이터를 분석할지
        interval_hours: 시간대별 집계 간격 (시간 단위)
        news_queryset: 뉴스 QuerySet (선택적)
        sns_queryset: SNS QuerySet (선택적)
        
    Returns:
        {
            'timelines': 키워드별 타임라인 데이터 딕셔너리,
            'common_time_labels': 공통 시간 레이블 리스트
        }
    """
    timelines = {}
    all_time_labels = set()
    
    for keyword in keywords:
        timeline_data = get_keyword_timeline(
            keyword, days, interval_hours, news_queryset, sns_queryset
        )
        timelines[keyword] = timeline_data
        all_time_labels.update(timeline_data['time_labels'])
    
    # 모든 시간 레이블 정렬
    common_time_labels = sorted(list(all_time_labels))
    
    return {
        'timelines': timelines,
        'common_time_labels': common_time_labels
    }


def get_keyword_timeline(
    keyword: str,
    days: int = 7,
    interval_hours: int = 6,  # 6시간 단위로 집계
    news_queryset=None,
    sns_queryset=None
) -> Dict[str, any]:
    """
    키워드의 시간대별 등장 빈도를 계산하여 타임라인 데이터를 생성합니다.
    
    시각화(그래프)에 사용할 수 있는 데이터를 반환합니다.
    
    Args:
        keyword: 분석할 키워드
        days: 최근 며칠간의 데이터를 분석할지
        interval_hours: 시간대별 집계 간격 (시간 단위)
        news_queryset: 뉴스 QuerySet (선택적)
        sns_queryset: SNS QuerySet (선택적)
        
    Returns:
        {
            'keyword': 키워드,
            'news_timeline': 뉴스 시간대별 등장 횟수 리스트,
            'sns_timeline': SNS 시간대별 등장 횟수 리스트,
            'time_labels': 시간대 레이블 리스트,
            'news_first_occurrence': 뉴스 최초 등장 시간,
            'sns_first_occurrence': SNS 최초 등장 시간
        }
    """
    from data_collector.models import NewsArticle, SocialMediaPost
    from collections import defaultdict
    
    # QuerySet 준비
    start_date = timezone.now() - timedelta(days=days)
    
    if news_queryset is None:
        news_queryset = NewsArticle.objects.filter(
            published_at__gte=start_date
        ).exclude(published_at__isnull=True)
    
    if sns_queryset is None:
        sns_queryset = SocialMediaPost.objects.filter(
            published_at__gte=start_date
        ).exclude(published_at__isnull=True)
    
    # 분석기 가져오기
    analyzer = get_analyzer()
    
    # 시간대별 집계를 위한 딕셔너리
    news_buckets = defaultdict(int)
    sns_buckets = defaultdict(int)
    
    news_first = None
    sns_first = None
    
    # 뉴스 처리
    for article in news_queryset:
        text = extract_text_from_news_article(article)
        if not text:
            continue
        
        keywords = analyzer.extract_keywords(text, min_length=2, exclude_stopwords=True)
        
        if keyword in keywords and article.published_at:
            # 시간대 버킷 계산 (interval_hours 단위)
            bucket_key = article.published_at.replace(
                minute=0, second=0, microsecond=0
            )
            # interval_hours 단위로 반올림
            hours_offset = bucket_key.hour % interval_hours
            bucket_key = bucket_key - timedelta(hours=hours_offset)
            
            news_buckets[bucket_key] += 1
            
            # 최초 등장 시간 기록
            if news_first is None or article.published_at < news_first:
                news_first = article.published_at
    
    # SNS 처리
    for post in sns_queryset:
        text = extract_text_from_sns_post(post)
        if not text:
            continue
        
        keywords = analyzer.extract_keywords(text, min_length=2, exclude_stopwords=True)
        
        if keyword in keywords and post.published_at:
            # 시간대 버킷 계산
            bucket_key = post.published_at.replace(
                minute=0, second=0, microsecond=0
            )
            hours_offset = bucket_key.hour % interval_hours
            bucket_key = bucket_key - timedelta(hours=hours_offset)
            
            sns_buckets[bucket_key] += 1
            
            # 최초 등장 시간 기록
            if sns_first is None or post.published_at < sns_first:
                sns_first = post.published_at
    
    # 모든 시간대 버킷 합치기
    all_buckets = set(news_buckets.keys()) | set(sns_buckets.keys())
    all_buckets = sorted(all_buckets)
    
    # 타임라인 데이터 생성
    news_timeline = [news_buckets.get(bucket, 0) for bucket in all_buckets]
    sns_timeline = [sns_buckets.get(bucket, 0) for bucket in all_buckets]
    
    # 시간 레이블 생성 (문자열 형식)
    time_labels = [bucket.strftime('%Y-%m-%d %H:%M') for bucket in all_buckets]
    
    return {
        'keyword': keyword,
        'news_timeline': news_timeline,
        'sns_timeline': sns_timeline,
        'time_labels': time_labels,
        'time_buckets': [bucket.isoformat() for bucket in all_buckets],  # ISO 형식
        'news_first_occurrence': news_first.isoformat() if news_first else None,
        'sns_first_occurrence': sns_first.isoformat() if sns_first else None,
        'interval_hours': interval_hours
    }

