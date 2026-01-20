import logging
import os
from typing import List, Dict, Optional, Tuple, Any
from collections import Counter, defaultdict
from datetime import timedelta
from django.utils import timezone
from data_collector.models import NewsArticle, SocialMediaPost
from PyKomoran import Komoran

logger = logging.getLogger(__name__)

# 불용어 리스트 캐시 (한 번만 로드)
_STOPWORDS_CACHE: Optional[set] = None
_STOPWORDS_FILE_MTIME: Optional[float] = None  # 파일 수정 시간

"""
주요 클래스 및 함수:

1. MorphologicalAnalyzer: 형태소 분석기 클래스
   - analyze(): 텍스트 형태소 분석
   - extract_nouns(): 명사 추출
   - extract_keywords(): 키워드 추출
   - get_keyword_frequency(): 키워드 빈도 계산
   - normalize_frequency(): 빈도 정규화

2. 유틸리티 함수:
   - get_analyzer(): 형태소 분석기 싱글톤 인스턴스 반환
   - extract_text_from_news_article(): 뉴스 기사에서 텍스트 추출
   - extract_text_from_sns_post(): SNS 게시물에서 텍스트 추출

3. 플랫폼별 분석 함수:
   - analyze_news_articles(): 뉴스 기사 키워드 분석
   - analyze_sns_posts(): SNS 게시물 키워드 분석
   - compare_platforms(): 뉴스와 SNS 플랫폼 비교 분석

4. 시간차 및 타임라인 분석:
   - analyze_time_lag(): 뉴스와 SNS 간 키워드 전파 패턴 분석
   - get_keyword_timeline(): 키워드 시간대별 등장 빈도 타임라인
   - get_multiple_keywords_timeline(): 여러 키워드 타임라인 일괄 생성
   - get_keyword_occurrence_times(): 키워드 등장 시간 정보 추출

5. 트렌드 분석:
   - detect_surge_keywords(): 플랫폼별 급상승 키워드 탐지
   - analyze_trend_synchronization(): 뉴스와 SNS 트렌드 동기화 분석
   - analyze_hourly_trends(): 시간대별 트렌드 변화 분석
   - analyze_engagement_keywords(): 참여도 기반 인기 키워드 분석
"""
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
        """기본 불용어 리스트 반환 (현재는 빈 집합)"""
        return set()
    
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
        articles = NewsArticle.objects.filter(category='정치')
        result = analyze_news_articles(queryset=articles)
        
        # 상위 10개 키워드만
        result = analyze_news_articles(days=7, top_n=10)
    """
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
        posts = SocialMediaPost.objects.filter(source__platform='reddit')
        result = analyze_sns_posts(queryset=posts)
    """
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
) -> Dict[str, Any]:
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
    
    # QuerySet 준비
    if news_queryset is None:
        start_date = timezone.now() - timedelta(days=days)
        news_queryset = NewsArticle.objects.filter(
            published_at__gte=start_date
        ).exclude(published_at__isnull=True).order_by('published_at')
    
    if sns_queryset is None:
        start_date = timezone.now() - timedelta(days=days)
        sns_queryset = SocialMediaPost.objects.filter(
            published_at__gte=start_date
        ).exclude(published_at__isnull=True).order_by('published_at')
    
    # 분석기 가져오기
    analyzer = get_analyzer()
    
    logger.info(f"뉴스 기사 형태소 분석 시작: {news_queryset.count()}개")
    news_keywords_map = {}
    for article in news_queryset:
        text = extract_text_from_news_article(article)
        if text:
            keywords = analyzer.extract_keywords(text, min_length=2, exclude_stopwords=True)
            news_keywords_map[article.id] = keywords
    
    logger.info(f"SNS 게시물 형태소 분석 시작: {sns_queryset.count()}개")
    sns_keywords_map = {}
    for post in sns_queryset:
        text = extract_text_from_sns_post(post)
        if text:
            keywords = analyzer.extract_keywords(text, min_length=2, exclude_stopwords=True)
            sns_keywords_map[post.id] = keywords
    
    logger.info("형태소 분석 완료. 키워드별 등장 시간 계산 시작")
    
    keyword_results = []
    news_to_sns_lags = []
    sns_to_news_lags = []
    
    for keyword in keywords:
        # 뉴스에서 등장한 게시물 찾기
        news_occurrences = []
        for article in news_queryset:
            if article.id in news_keywords_map and keyword in news_keywords_map[article.id]:
                if article.published_at:
                    news_occurrences.append(article.published_at)
        
        # SNS에서 등장한 게시물 찾기
        sns_occurrences = []
        for post in sns_queryset:
            if post.id in sns_keywords_map and keyword in sns_keywords_map[post.id]:
                if post.published_at:
                    sns_occurrences.append(post.published_at)
        
        # 최초/최종 등장 시간 계산
        news_first = min(news_occurrences) if news_occurrences else None
        sns_first = min(sns_occurrences) if sns_occurrences else None
        
        # 시간차 계산
        result = {
            'keyword': keyword,
            'news_first_occurrence': news_first,
            'sns_first_occurrence': sns_first,
            'news_occurrence_count': len(news_occurrences),
            'sns_occurrence_count': len(sns_occurrences),
            'direction': None,
            'time_lag_hours': None,
            'time_lag_seconds': None,
            'time_lag_text': None
        }
        
        if news_first and sns_first:
            # 두 플랫폼 모두에서 등장
            if news_first < sns_first:
                # 뉴스가 먼저
                time_lag = sns_first - news_first
                result['direction'] = 'news_to_sns'
                time_lag_seconds = time_lag.total_seconds()
                result['time_lag_seconds'] = time_lag_seconds
                result['time_lag_text'] = str(time_lag)
                result['time_lag_hours'] = time_lag_seconds / 3600
                news_to_sns_lags.append(time_lag_seconds / 3600)
            elif sns_first < news_first:
                # SNS가 먼저
                time_lag = news_first - sns_first
                result['direction'] = 'sns_to_news'
                time_lag_seconds = time_lag.total_seconds()
                result['time_lag_seconds'] = time_lag_seconds
                result['time_lag_text'] = str(time_lag)
                result['time_lag_hours'] = time_lag_seconds / 3600
                sns_to_news_lags.append(time_lag_seconds / 3600)
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
    
    최적화: 모든 게시물을 한 번만 형태소 분석하고, 각 키워드에 대해 재사용합니다.
    
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
    
    # 최적화: 모든 게시물을 한 번만 형태소 분석하고 결과 재사용
    analyzer = get_analyzer()
    
    logger.info(f"뉴스 기사 형태소 분석 시작: {news_queryset.count()}개")
    news_keywords_map = {}
    for article in news_queryset:
        text = extract_text_from_news_article(article)
        if text:
            keywords_extracted = analyzer.extract_keywords(text, min_length=2, exclude_stopwords=True)
            news_keywords_map[article.id] = keywords_extracted
    
    logger.info(f"SNS 게시물 형태소 분석 시작: {sns_queryset.count()}개")
    sns_keywords_map = {}
    for post in sns_queryset:
        text = extract_text_from_sns_post(post)
        if text:
            keywords_extracted = analyzer.extract_keywords(text, min_length=2, exclude_stopwords=True)
            sns_keywords_map[post.id] = keywords_extracted
    
    logger.info(f"형태소 분석 완료. {len(keywords)}개 키워드 타임라인 생성 시작")
    
    timelines = {}
    all_time_labels = set()
    
    # 각 키워드에 대해 타임라인 생성 (형태소 분석 결과 재사용)
    for keyword in keywords:
        news_buckets = defaultdict(int)
        sns_buckets = defaultdict(int)
        news_first = None
        sns_first = None
        
        # 뉴스 처리 (메모리에서 키워드 검색)
        for article in news_queryset:
            if article.id in news_keywords_map and keyword in news_keywords_map[article.id]:
                if article.published_at:
                    bucket_key = article.published_at.replace(
                        minute=0, second=0, microsecond=0
                    )
                    hours_offset = bucket_key.hour % interval_hours
                    bucket_key = bucket_key - timedelta(hours=hours_offset)
                    
                    news_buckets[bucket_key] += 1
                    
                    if news_first is None or article.published_at < news_first:
                        news_first = article.published_at
        
        # SNS 처리 (메모리에서 키워드 검색)
        for post in sns_queryset:
            if post.id in sns_keywords_map and keyword in sns_keywords_map[post.id]:
                if post.published_at:
                    bucket_key = post.published_at.replace(
                        minute=0, second=0, microsecond=0
                    )
                    hours_offset = bucket_key.hour % interval_hours
                    bucket_key = bucket_key - timedelta(hours=hours_offset)
                    
                    sns_buckets[bucket_key] += 1
                    
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
        
        timeline_data = {
            'keyword': keyword,
            'news_timeline': news_timeline,
            'sns_timeline': sns_timeline,
            'time_labels': time_labels,
            'time_buckets': [bucket.isoformat() for bucket in all_buckets],
            'news_first_occurrence': news_first.isoformat() if news_first else None,
            'sns_first_occurrence': sns_first.isoformat() if sns_first else None,
            'interval_hours': interval_hours
        }
        
        timelines[keyword] = timeline_data
        all_time_labels.update(time_labels)
    
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
    
    # 최적화: 모든 게시물을 한 번만 형태소 분석하고 결과 재사용
    logger.info(f"뉴스 기사 형태소 분석 시작: {news_queryset.count()}개")
    news_keywords_map = {}
    for article in news_queryset:
        text = extract_text_from_news_article(article)
        if text:
            keywords_extracted = analyzer.extract_keywords(text, min_length=2, exclude_stopwords=True)
            news_keywords_map[article.id] = keywords_extracted
    
    logger.info(f"SNS 게시물 형태소 분석 시작: {sns_queryset.count()}개")
    sns_keywords_map = {}
    for post in sns_queryset:
        text = extract_text_from_sns_post(post)
        if text:
            keywords_extracted = analyzer.extract_keywords(text, min_length=2, exclude_stopwords=True)
            sns_keywords_map[post.id] = keywords_extracted
    
    logger.info("형태소 분석 완료. 타임라인 집계 시작")
    
    # 시간대별 집계를 위한 딕셔너리
    news_buckets = defaultdict(int)
    sns_buckets = defaultdict(int)
    
    news_first = None
    sns_first = None
    
    # 뉴스 처리 (메모리에서 키워드 검색)
    for article in news_queryset:
        if article.id in news_keywords_map and keyword in news_keywords_map[article.id]:
            if article.published_at:
                bucket_key = article.published_at.replace(
                    minute=0, second=0, microsecond=0
                )
                hours_offset = bucket_key.hour % interval_hours
                bucket_key = bucket_key - timedelta(hours=hours_offset)
                
                news_buckets[bucket_key] += 1
                
                if news_first is None or article.published_at < news_first:
                    news_first = article.published_at
    
    # SNS 처리 (메모리에서 키워드 검색)
    for post in sns_queryset:
        if post.id in sns_keywords_map and keyword in sns_keywords_map[post.id]:
            if post.published_at:
                bucket_key = post.published_at.replace(
                    minute=0, second=0, microsecond=0
                )
                hours_offset = bucket_key.hour % interval_hours
                bucket_key = bucket_key - timedelta(hours=hours_offset)
                
                sns_buckets[bucket_key] += 1
                
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


def detect_surge_keywords(
    platform: str = 'both',  # 'news', 'sns', 'both'
    days: int = 7,
    interval_hours: int = 6,
    surge_threshold: float = 2.0,  # 2배 이상 증가 시 급상승으로 간주
    min_frequency: float = 0.001,
    top_n: Optional[int] = None,
    news_queryset=None,
    sns_queryset=None
) -> Dict[str, Any]:
    """
    플랫폼별 급상승 키워드를 탐지합니다.
    
    시간대별 키워드 빈도를 비교하여 급격히 증가한 키워드를 찾습니다.
    
    Args:
        platform: 분석할 플랫폼 ('news', 'sns', 'both')
        days: 최근 며칠간의 데이터를 분석할지
        interval_hours: 시간대별 집계 간격 (시간 단위)
        surge_threshold: 급상승 임계값 (이전 시간대 대비 배수, 기본값: 2.0 = 2배)
        min_frequency: 최소 상대 빈도 (이 값보다 작은 키워드는 제외)
        top_n: 상위 N개 급상승 키워드만 반환 (None이면 전체)
        news_queryset: 뉴스 QuerySet (선택적)
        sns_queryset: SNS QuerySet (선택적)
        
    Returns:
        {
            'news_surge_keywords': 뉴스 급상승 키워드 리스트,
            'sns_surge_keywords': SNS 급상승 키워드 리스트,
            'summary': 요약 통계
        }
    """
    # QuerySet 준비
    start_date = timezone.now() - timedelta(days=days)
    
    if news_queryset is None:
        news_queryset = NewsArticle.objects.filter(
            published_at__gte=start_date
        ).exclude(published_at__isnull=True).order_by('published_at')
    
    if sns_queryset is None:
        sns_queryset = SocialMediaPost.objects.filter(
            published_at__gte=start_date
        ).exclude(published_at__isnull=True).order_by('published_at')
    
    analyzer = get_analyzer()
    
    result = {
        'news_surge_keywords': [],
        'sns_surge_keywords': [],
        'summary': {}
    }
    
    # 뉴스 급상승 키워드 탐지
    if platform in ('news', 'both'):
        logger.info(f"뉴스 급상승 키워드 탐지 시작: {news_queryset.count()}개 기사")
        
        # 시간대별 키워드 빈도 계산
        news_keywords_map = {}
        for article in news_queryset:
            text = extract_text_from_news_article(article)
            if text:
                keywords = analyzer.extract_keywords(text, min_length=2, exclude_stopwords=True)
                news_keywords_map[article.id] = {
                    'keywords': keywords,
                    'published_at': article.published_at
                }
        
        # 시간대별 버킷으로 분류
        time_buckets = defaultdict(lambda: defaultdict(int))
        for article_id, data in news_keywords_map.items():
            if data['published_at']:
                bucket_key = data['published_at'].replace(
                    minute=0, second=0, microsecond=0
                )
                hours_offset = bucket_key.hour % interval_hours
                bucket_key = bucket_key - timedelta(hours=hours_offset)
                
                for keyword in data['keywords']:
                    time_buckets[bucket_key][keyword] += 1
        
        # 시간대별로 정렬
        sorted_buckets = sorted(time_buckets.keys())
        
        if len(sorted_buckets) >= 2:
            # 마지막 시간대와 그 이전 시간대 비교
            current_bucket = sorted_buckets[-1]
            previous_bucket = sorted_buckets[-2]
            
            current_freq = time_buckets[current_bucket]
            previous_freq = time_buckets[previous_bucket]
            
            # 전체 빈도로 정규화
            current_total = sum(current_freq.values())
            previous_total = sum(previous_freq.values())
            
            if current_total > 0 and previous_total > 0:
                surge_keywords = []
                for keyword, count in current_freq.items():
                    current_norm = count / current_total if current_total > 0 else 0
                    previous_norm = previous_freq.get(keyword, 0) / previous_total if previous_total > 0 else 0
                    
                    if current_norm >= min_frequency and previous_norm > 0:
                        growth_ratio = current_norm / previous_norm if previous_norm > 0 else 0
                        
                        if growth_ratio >= surge_threshold:
                            surge_keywords.append({
                                'keyword': keyword,
                                'current_frequency': current_norm,
                                'previous_frequency': previous_norm,
                                'growth_ratio': growth_ratio,
                                'current_count': count,
                                'previous_count': previous_freq.get(keyword, 0),
                                'time_bucket': current_bucket.isoformat()
                            })
                
                # 증가율 순으로 정렬
                surge_keywords.sort(key=lambda x: x['growth_ratio'], reverse=True)
                
                if top_n and top_n > 0:
                    surge_keywords = surge_keywords[:top_n]
                
                result['news_surge_keywords'] = surge_keywords
                logger.info(f"뉴스 급상승 키워드 {len(surge_keywords)}개 탐지 완료")
    
    # SNS 급상승 키워드 탐지
    if platform in ('sns', 'both'):
        logger.info(f"SNS 급상승 키워드 탐지 시작: {sns_queryset.count()}개 게시물")
        
        # 시간대별 키워드 빈도 계산
        sns_keywords_map = {}
        for post in sns_queryset:
            text = extract_text_from_sns_post(post)
            if text:
                keywords = analyzer.extract_keywords(text, min_length=2, exclude_stopwords=True)
                sns_keywords_map[post.id] = {
                    'keywords': keywords,
                    'published_at': post.published_at
                }
        
        # 시간대별 버킷으로 분류
        time_buckets = defaultdict(lambda: defaultdict(int))
        for post_id, data in sns_keywords_map.items():
            if data['published_at']:
                bucket_key = data['published_at'].replace(
                    minute=0, second=0, microsecond=0
                )
                hours_offset = bucket_key.hour % interval_hours
                bucket_key = bucket_key - timedelta(hours=hours_offset)
                
                for keyword in data['keywords']:
                    time_buckets[bucket_key][keyword] += 1
        
        # 시간대별로 정렬
        sorted_buckets = sorted(time_buckets.keys())
        
        if len(sorted_buckets) >= 2:
            # 마지막 시간대와 그 이전 시간대 비교
            current_bucket = sorted_buckets[-1]
            previous_bucket = sorted_buckets[-2]
            
            current_freq = time_buckets[current_bucket]
            previous_freq = time_buckets[previous_bucket]
            
            # 전체 빈도로 정규화
            current_total = sum(current_freq.values())
            previous_total = sum(previous_freq.values())
            
            if current_total > 0 and previous_total > 0:
                surge_keywords = []
                for keyword, count in current_freq.items():
                    current_norm = count / current_total if current_total > 0 else 0
                    previous_norm = previous_freq.get(keyword, 0) / previous_total if previous_total > 0 else 0
                    
                    if current_norm >= min_frequency and previous_norm > 0:
                        growth_ratio = current_norm / previous_norm if previous_norm > 0 else 0
                        
                        if growth_ratio >= surge_threshold:
                            surge_keywords.append({
                                'keyword': keyword,
                                'current_frequency': current_norm,
                                'previous_frequency': previous_norm,
                                'growth_ratio': growth_ratio,
                                'current_count': count,
                                'previous_count': previous_freq.get(keyword, 0),
                                'time_bucket': current_bucket.isoformat()
                            })
                
                # 증가율 순으로 정렬
                surge_keywords.sort(key=lambda x: x['growth_ratio'], reverse=True)
                
                if top_n and top_n > 0:
                    surge_keywords = surge_keywords[:top_n]
                
                result['sns_surge_keywords'] = surge_keywords
                logger.info(f"SNS 급상승 키워드 {len(surge_keywords)}개 탐지 완료")
    
    # 요약 통계
    result['summary'] = {
        'platform': platform,
        'days': days,
        'interval_hours': interval_hours,
        'surge_threshold': surge_threshold,
        'news_surge_count': len(result['news_surge_keywords']),
        'sns_surge_count': len(result['sns_surge_keywords'])
    }
    
    return result


def analyze_trend_synchronization(
    days: int = 7,
    interval_hours: int = 6,
    min_frequency: float = 0.001,
    top_n: Optional[int] = None,
    news_queryset=None,
    sns_queryset=None
) -> Dict[str, Any]:
    """
    뉴스와 SNS의 트렌드 동기화 정도를 분석합니다.
    
    시간대별 키워드 빈도 변화 패턴을 비교하여 두 플랫폼이 얼마나 동기화되어 있는지 측정합니다.
    
    Args:
        days: 최근 며칠간의 데이터를 분석할지
        interval_hours: 시간대별 집계 간격 (시간 단위)
        min_frequency: 최소 상대 빈도 (이 값보다 작은 키워드는 제외)
        top_n: 상위 N개 키워드만 분석 (None이면 전체)
        news_queryset: 뉴스 QuerySet (선택적)
        sns_queryset: SNS QuerySet (선택적)
        
    Returns:
        {
            'synchronized_keywords': 동기화된 키워드 리스트 (상관관계 높음),
            'desynchronized_keywords': 비동기화된 키워드 리스트 (상관관계 낮음),
            'correlation_scores': 키워드별 상관관계 점수,
            'summary': 요약 통계
        }
    """
    # QuerySet 준비
    start_date = timezone.now() - timedelta(days=days)
    
    if news_queryset is None:
        news_queryset = NewsArticle.objects.filter(
            published_at__gte=start_date
        ).exclude(published_at__isnull=True).order_by('published_at')
    
    if sns_queryset is None:
        sns_queryset = SocialMediaPost.objects.filter(
            published_at__gte=start_date
        ).exclude(published_at__isnull=True).order_by('published_at')
    
    analyzer = get_analyzer()
    
    logger.info(f"트렌드 동기화 분석 시작: 뉴스 {news_queryset.count()}개, SNS {sns_queryset.count()}개")
    
    # 형태소 분석 (최적화)
    news_keywords_map = {}
    for article in news_queryset:
        text = extract_text_from_news_article(article)
        if text:
            keywords = analyzer.extract_keywords(text, min_length=2, exclude_stopwords=True)
            news_keywords_map[article.id] = {
                'keywords': keywords,
                'published_at': article.published_at
            }
    
    sns_keywords_map = {}
    for post in sns_queryset:
        text = extract_text_from_sns_post(post)
        if text:
            keywords = analyzer.extract_keywords(text, min_length=2, exclude_stopwords=True)
            sns_keywords_map[post.id] = {
                'keywords': keywords,
                'published_at': post.published_at
            }
    
    # 시간대별 키워드 빈도 계산
    news_time_buckets = defaultdict(lambda: defaultdict(int))
    for _, data in news_keywords_map.items():
        if data['published_at']:
            bucket_key = data['published_at'].replace(
                minute=0, second=0, microsecond=0
            )
            hours_offset = bucket_key.hour % interval_hours
            bucket_key = bucket_key - timedelta(hours=hours_offset)
            
            for keyword in data['keywords']:
                news_time_buckets[bucket_key][keyword] += 1
    
    sns_time_buckets = defaultdict(lambda: defaultdict(int))
    for _, data in sns_keywords_map.items():
        if data['published_at']:
            bucket_key = data['published_at'].replace(
                minute=0, second=0, microsecond=0
            )
            hours_offset = bucket_key.hour % interval_hours
            bucket_key = bucket_key - timedelta(hours=hours_offset)
            
            for keyword in data['keywords']:
                sns_time_buckets[bucket_key][keyword] += 1
    
    # 모든 시간대 버킷 합치기
    all_buckets = sorted(set(news_time_buckets.keys()) | set(sns_time_buckets.keys()))
    
    # 공통 키워드 찾기
    all_news_keywords = set()
    for bucket in news_time_buckets.values():
        all_news_keywords.update(bucket.keys())
    
    all_sns_keywords = set()
    for bucket in sns_time_buckets.values():
        all_sns_keywords.update(bucket.keys())
    
    common_keywords = all_news_keywords & all_sns_keywords
    
    # 각 키워드에 대해 시간대별 빈도 시퀀스 생성 및 상관관계 계산
    correlation_scores = []
    
    for keyword in common_keywords:
        news_sequence = []
        sns_sequence = []
        
        for bucket in all_buckets:
            news_count = news_time_buckets[bucket].get(keyword, 0)
            sns_count = sns_time_buckets[bucket].get(keyword, 0)
            
            # 정규화 (해당 시간대의 전체 키워드 수로 나눔)
            news_total = sum(news_time_buckets[bucket].values())
            sns_total = sum(sns_time_buckets[bucket].values())
            
            news_norm = news_count / news_total if news_total > 0 else 0
            sns_norm = sns_count / sns_total if sns_total > 0 else 0
            
            if news_norm >= min_frequency or sns_norm >= min_frequency:
                news_sequence.append(news_norm)
                sns_sequence.append(sns_norm)
        
        # 상관관계 계산 (피어슨 상관계수)
        if len(news_sequence) >= 2 and len(sns_sequence) >= 2:
            # 간단한 상관관계 계산
            n = len(news_sequence)
            news_mean = sum(news_sequence) / n
            sns_mean = sum(sns_sequence) / n
            
            numerator = sum((news_sequence[i] - news_mean) * (sns_sequence[i] - sns_mean) 
                          for i in range(n))
            
            news_var = sum((x - news_mean) ** 2 for x in news_sequence)
            sns_var = sum((x - sns_mean) ** 2 for x in sns_sequence)
            
            denominator = (news_var * sns_var) ** 0.5
            
            if denominator > 0:
                correlation = numerator / denominator
            else:
                correlation = 0.0
            
            # 평균 빈도 계산
            avg_news_freq = news_mean
            avg_sns_freq = sns_mean
            
            correlation_scores.append({
                'keyword': keyword,
                'correlation': correlation,
                'avg_news_frequency': avg_news_freq,
                'avg_sns_frequency': avg_sns_freq,
                'news_sequence': news_sequence,
                'sns_sequence': sns_sequence
            })
    
    # 상관관계 순으로 정렬
    correlation_scores.sort(key=lambda x: abs(x['correlation']), reverse=True)
    
    # 동기화/비동기화 키워드 분류 (상관관계 0.7 이상 = 동기화, 0.3 미만 = 비동기화)
    synchronized_keywords = [
        item for item in correlation_scores 
        if item['correlation'] >= 0.7
    ]
    desynchronized_keywords = [
        item for item in correlation_scores 
        if item['correlation'] < 0.3
    ]
    
    if top_n and top_n > 0:
        synchronized_keywords = synchronized_keywords[:top_n]
        desynchronized_keywords = desynchronized_keywords[:top_n]
    
    # 요약 통계
    avg_correlation = sum(item['correlation'] for item in correlation_scores) / len(correlation_scores) if correlation_scores else 0.0
    
    summary = {
        'total_common_keywords': len(common_keywords),
        'analyzed_keywords': len(correlation_scores),
        'synchronized_count': len(synchronized_keywords),
        'desynchronized_count': len(desynchronized_keywords),
        'avg_correlation': avg_correlation,
        'time_buckets_count': len(all_buckets)
    }
    
    logger.info(
        f"트렌드 동기화 분석 완료: "
        f"동기화 {summary['synchronized_count']}개, "
        f"비동기화 {summary['desynchronized_count']}개, "
        f"평균 상관관계 {avg_correlation:.3f}"
    )
    
    return {
        'synchronized_keywords': synchronized_keywords,
        'desynchronized_keywords': desynchronized_keywords,
        'correlation_scores': correlation_scores,
        'summary': summary
    }


def analyze_hourly_trends(
    platform: str = 'both',  # 'news', 'sns', 'both'
    days: int = 7,
    min_frequency: float = 0.001,
    top_n: Optional[int] = None,
    news_queryset=None,
    sns_queryset=None
) -> Dict[str, Any]:
    """
    시간대별 트렌드 변화를 분석합니다.
    
    시간대(0시~23시)별로 키워드 빈도 변화를 분석하여 시간대별 트렌드 패턴을 파악합니다.
    
    Args:
        platform: 분석할 플랫폼 ('news', 'sns', 'both')
        days: 최근 며칠간의 데이터를 분석할지
        min_frequency: 최소 상대 빈도 (이 값보다 작은 키워드는 제외)
        top_n: 시간대별 상위 N개 키워드만 반환 (None이면 전체)
        news_queryset: 뉴스 QuerySet (선택적)
        sns_queryset: SNS QuerySet (선택적)
        
    Returns:
        {
            'news_hourly_trends': 뉴스 시간대별 트렌드,
            'sns_hourly_trends': SNS 시간대별 트렌드,
            'summary': 요약 통계
        }
    """
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
    
    analyzer = get_analyzer()
    
    result = {
        'news_hourly_trends': {},
        'sns_hourly_trends': {},
        'summary': {}
    }
    
    # 뉴스 시간대별 트렌드 분석
    if platform in ('news', 'both'):
        logger.info(f"뉴스 시간대별 트렌드 분석 시작: {news_queryset.count()}개 기사")
        
        # 시간대별 키워드 빈도 계산
        hourly_keywords = defaultdict(lambda: defaultdict(int))
        news_keywords_map = {}
        
        for article in news_queryset:
            text = extract_text_from_news_article(article)
            if text:
                keywords = analyzer.extract_keywords(text, min_length=2, exclude_stopwords=True)
                news_keywords_map[article.id] = keywords
                
                if article.published_at:
                    hour = article.published_at.hour
                    for keyword in keywords:
                        hourly_keywords[hour][keyword] += 1
        
        # 시간대별로 정규화 및 상위 키워드 추출
        for hour in range(24):
            if hour in hourly_keywords:
                hour_freq = hourly_keywords[hour]
                total = sum(hour_freq.values())
                
                if total > 0:
                    # 정규화
                    normalized = {
                        k: v / total for k, v in hour_freq.items()
                        if (v / total) >= min_frequency
                    }
                    
                    # 상위 키워드 추출
                    sorted_keywords = sorted(
                        normalized.items(),
                        key=lambda x: x[1],
                        reverse=True
                    )
                    
                    if top_n and top_n > 0:
                        sorted_keywords = sorted_keywords[:top_n]
                    
                    result['news_hourly_trends'][hour] = {
                        'keywords': [
                            {'keyword': k, 'frequency': v}
                            for k, v in sorted_keywords
                        ],
                        'total_keywords': len(normalized),
                        'total_count': total
                    }
        
        logger.info(f"뉴스 시간대별 트렌드 분석 완료")
    
    # SNS 시간대별 트렌드 분석
    if platform in ('sns', 'both'):
        logger.info(f"SNS 시간대별 트렌드 분석 시작: {sns_queryset.count()}개 게시물")
        
        # 시간대별 키워드 빈도 계산
        hourly_keywords = defaultdict(lambda: defaultdict(int))
        sns_keywords_map = {}
        
        for post in sns_queryset:
            text = extract_text_from_sns_post(post)
            if text:
                keywords = analyzer.extract_keywords(text, min_length=2, exclude_stopwords=True)
                sns_keywords_map[post.id] = keywords
                
                if post.published_at:
                    hour = post.published_at.hour
                    for keyword in keywords:
                        hourly_keywords[hour][keyword] += 1
        
        # 시간대별로 정규화 및 상위 키워드 추출
        for hour in range(24):
            if hour in hourly_keywords:
                hour_freq = hourly_keywords[hour]
                total = sum(hour_freq.values())
                
                if total > 0:
                    # 정규화
                    normalized = {
                        k: v / total for k, v in hour_freq.items()
                        if (v / total) >= min_frequency
                    }
                    
                    # 상위 키워드 추출
                    sorted_keywords = sorted(
                        normalized.items(),
                        key=lambda x: x[1],
                        reverse=True
                    )
                    
                    if top_n and top_n > 0:
                        sorted_keywords = sorted_keywords[:top_n]
                    
                    result['sns_hourly_trends'][hour] = {
                        'keywords': [
                            {'keyword': k, 'frequency': v}
                            for k, v in sorted_keywords
                        ],
                        'total_keywords': len(normalized),
                        'total_count': total
                    }
        
        logger.info(f"SNS 시간대별 트렌드 분석 완료")
    
    # 요약 통계
    result['summary'] = {
        'platform': platform,
        'days': days,
        'news_hours_analyzed': len(result['news_hourly_trends']),
        'sns_hours_analyzed': len(result['sns_hourly_trends'])
    }
    
    return result


def analyze_engagement_keywords(
    days: int = 7,
    min_frequency: float = 0.001,
    top_n: Optional[int] = None,
    engagement_weights: Optional[Dict[str, float]] = None,
    sns_queryset=None
) -> Dict[str, Any]:
    """
    참여도 기반 인기 키워드를 분석합니다.
    
    SNS 게시물의 참여도 메트릭(조회수, 댓글수, 좋아요수, 공유수)을 활용하여
    실제 반응이 높은 키워드를 식별합니다.
    
    Args:
        days: 최근 며칠간의 데이터를 분석할지
        min_frequency: 최소 상대 빈도 (이 값보다 작은 키워드는 제외)
        top_n: 상위 N개 키워드만 반환 (None이면 전체)
        engagement_weights: 참여도 가중치 딕셔너리
            - 기본값: {'views': 0.1, 'comments': 0.3, 'likes': 0.4, 'shares': 0.2}
            - 각 메트릭의 중요도를 조정할 수 있음
        sns_queryset: SNS QuerySet (선택적)
        
    Returns:
        {
            'engagement_keywords': 참여도 기반 키워드 리스트,
            'viral_keywords': 바이럴 키워드 리스트 (참여도 급상승),
            'summary': 요약 통계
        }
    """
    # QuerySet 준비
    start_date = timezone.now() - timedelta(days=days)
    
    if sns_queryset is None:
        sns_queryset = SocialMediaPost.objects.filter(
            published_at__gte=start_date
        ).exclude(published_at__isnull=True)
    
    # 참여도 가중치 설정 (기본값)
    if engagement_weights is None:
        engagement_weights = {
            'views': 0.1,
            'comments': 0.3,
            'likes': 0.4,
            'shares': 0.2
        }
    
    analyzer = get_analyzer()
    
    logger.info(f"참여도 기반 키워드 분석 시작: {sns_queryset.count()}개 게시물")
    
    # 키워드별 참여도 집계
    keyword_engagement = defaultdict(lambda: {
        'total_engagement': 0.0,
        'post_count': 0,
        'total_views': 0,
        'total_comments': 0,
        'total_likes': 0,
        'total_shares': 0,
        'posts': []
    })
    
    # 형태소 분석 및 참여도 계산
    for post in sns_queryset:
        text = extract_text_from_sns_post(post)
        if not text:
            continue
        
        # 키워드 추출
        keywords = analyzer.extract_keywords(text, min_length=2, exclude_stopwords=True)
        
        # 참여도 점수 계산
        views = post.views_count or 0
        comments = post.comments_count or 0
        likes = post.likes_count or 0
        shares = post.shares_count or 0
        
        engagement_score = (
            views * engagement_weights['views'] +
            comments * engagement_weights['comments'] +
            likes * engagement_weights['likes'] +
            shares * engagement_weights['shares']
        )
        
        # 각 키워드에 참여도 점수 추가
        for keyword in keywords:
            keyword_engagement[keyword]['total_engagement'] += engagement_score
            keyword_engagement[keyword]['post_count'] += 1
            keyword_engagement[keyword]['total_views'] += views
            keyword_engagement[keyword]['total_comments'] += comments
            keyword_engagement[keyword]['total_likes'] += likes
            keyword_engagement[keyword]['total_shares'] += shares
            keyword_engagement[keyword]['posts'].append({
                'post_id': post.id,
                'engagement_score': engagement_score,
                'views': views,
                'comments': comments,
                'likes': likes,
                'shares': shares
            })
    
    # 키워드별 평균 참여도 계산 및 정규화
    total_posts = sns_queryset.count()
    engagement_keywords = []
    
    for keyword, data in keyword_engagement.items():
        post_count = data['post_count']
        
        # 최소 빈도 필터링
        frequency = post_count / total_posts if total_posts > 0 else 0
        if frequency < min_frequency:
            continue
        
        # 평균 참여도 계산
        avg_engagement = data['total_engagement'] / post_count if post_count > 0 else 0
        avg_views = data['total_views'] / post_count if post_count > 0 else 0
        avg_comments = data['total_comments'] / post_count if post_count > 0 else 0
        avg_likes = data['total_likes'] / post_count if post_count > 0 else 0
        avg_shares = data['total_shares'] / post_count if post_count > 0 else 0
        
        engagement_keywords.append({
            'keyword': keyword,
            'frequency': frequency,
            'post_count': post_count,
            'avg_engagement_score': avg_engagement,
            'total_engagement_score': data['total_engagement'],
            'avg_views': avg_views,
            'avg_comments': avg_comments,
            'avg_likes': avg_likes,
            'avg_shares': avg_shares,
            'total_views': data['total_views'],
            'total_comments': data['total_comments'],
            'total_likes': data['total_likes'],
            'total_shares': data['total_shares']
        })
    
    # 평균 참여도 순으로 정렬
    engagement_keywords.sort(key=lambda x: x['avg_engagement_score'], reverse=True)
    
    # top_n 적용
    if top_n and top_n > 0:
        engagement_keywords = engagement_keywords[:top_n]
    
    # 바이럴 키워드 탐지 (참여도가 높으면서 최근 급상승한 키워드)
    viral_keywords = []
    if len(engagement_keywords) > 0:
        # 상위 20% 키워드 중에서 최근 참여도가 높은 것들을 바이럴로 간주
        top_20_percent = max(1, int(len(engagement_keywords) * 0.2))
        top_keywords = engagement_keywords[:top_20_percent]
        
        # 최근 게시물의 참여도가 평균보다 높은 키워드 찾기
        for item in top_keywords:
            keyword = item['keyword']
            keyword_data = keyword_engagement[keyword]
            
            # 최근 게시물들의 참여도 확인 (최근 1일)
            recent_cutoff = timezone.now() - timedelta(days=1)
            recent_posts = [
                p for p in keyword_data['posts']
                if sns_queryset.filter(id=p['post_id'], published_at__gte=recent_cutoff).exists()
            ]
            
            if recent_posts:
                recent_avg_engagement = sum(p['engagement_score'] for p in recent_posts) / len(recent_posts)
                
                # 최근 평균이 전체 평균보다 높으면 바이럴로 간주
                if recent_avg_engagement > item['avg_engagement_score'] * 1.5:
                    viral_keywords.append({
                        **item,
                        'recent_avg_engagement': recent_avg_engagement,
                        'recent_post_count': len(recent_posts),
                        'viral_score': recent_avg_engagement / item['avg_engagement_score'] if item['avg_engagement_score'] > 0 else 0
                    })
        
        # 바이럴 점수 순으로 정렬
        viral_keywords.sort(key=lambda x: x.get('viral_score', 0), reverse=True)
    
    # 요약 통계
    summary = {
        'days': days,
        'total_posts': total_posts,
        'total_keywords': len(engagement_keywords),
        'viral_keywords_count': len(viral_keywords),
        'engagement_weights': engagement_weights,
        'top_engagement_score': engagement_keywords[0]['avg_engagement_score'] if engagement_keywords else 0,
        'avg_engagement_score': sum(item['avg_engagement_score'] for item in engagement_keywords) / len(engagement_keywords) if engagement_keywords else 0
    }
    
    logger.info(
        f"참여도 기반 키워드 분석 완료: "
        f"키워드 {len(engagement_keywords)}개, "
        f"바이럴 키워드 {len(viral_keywords)}개"
    )
    
    return {
        'engagement_keywords': engagement_keywords,
        'viral_keywords': viral_keywords,
        'summary': summary
    }
