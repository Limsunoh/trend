"""
번역 서비스 모듈

deep-translator (Google Translate)를 사용하여 텍스트를 번역합니다.
주로 Reddit 게시물의 영어 내용을 한국어로 번역하는 데 사용됩니다.
"""

import logging
import re
import time
from typing import Optional
from html import unescape
from bs4 import BeautifulSoup
from deep_translator import GoogleTranslator

logger = logging.getLogger(__name__)


class TranslationService:
    """
    Google Translate 기반 번역 서비스 (deep-translator 사용)
    
    싱글톤 패턴으로 번역기를 재사용하여 효율적으로 사용합니다.
    """
    
    _instance = None
    _translator = None
    
    def __new__(cls):
        """싱글톤 패턴 구현"""
        if cls._instance is None:
            cls._instance = super(TranslationService, cls).__new__(cls)
        return cls._instance
    
    def __init__(self):
        """번역 서비스 초기화"""
        if not hasattr(self, 'initialized'):
            self.logger = logging.getLogger(__name__)
            self.initialized = True
    
    def _get_translator(self, source_lang: str = 'en', target_lang: str = 'ko'):
        """
        Google Translator 인스턴스 가져오기 (재사용)
        
        Args:
            source_lang: 원본 언어 코드 (기본값: 'en')
            target_lang: 목표 언어 코드 (기본값: 'ko')
            
        Returns:
            GoogleTranslator 인스턴스
        """
        # 언어 쌍이 바뀌면 새로운 인스턴스 생성
        cache_key = f"{source_lang}_{target_lang}"
        if self._translator is None or not hasattr(self, '_cache_key') or self._cache_key != cache_key:
            try:
                self._translator = GoogleTranslator(source=source_lang, target=target_lang)
                self._cache_key = cache_key
            except Exception as e:
                self.logger.error(f"Google Translator 생성 실패: {str(e)}", exc_info=True)
                raise
        return self._translator
    
    def _clean_text(self, text: str) -> str:
        """
        번역 전 텍스트 정리 (HTML 태그 제거, 엔티티 디코딩)
        
        Args:
            text: 정리할 텍스트
            
        Returns:
            정리된 텍스트
        """
        if not text:
            return text
        
        # HTML 엔티티 디코딩 (&#32; -> 공백, &amp; -> & 등)
        text = unescape(text)
        
        # BeautifulSoup으로 HTML 태그 제거
        try:
            soup = BeautifulSoup(text, 'html.parser')
            text = soup.get_text(separator=' ', strip=True)
        except Exception:
            # BeautifulSoup 실패 시 간단한 정규식으로 HTML 태그 제거
            text = re.sub(r'<[^>]+>', '', text)
        
        # 연속된 공백 정리
        text = re.sub(r'\s+', ' ', text)
        
        return text.strip()
    
    def translate_text(
        self,
        text: str,
        source_lang: str = 'en',
        target_lang: str = 'ko',
        model_name: Optional[str] = None  # 호환성을 위해 유지 (사용 안 함)
    ) -> str:
        """
        텍스트를 번역합니다.
        
        Args:
            text: 번역할 텍스트
            source_lang: 원본 언어 (기본값: 'en')
            target_lang: 목표 언어 (기본값: 'ko')
            model_name: 사용하지 않음 (호환성을 위해 유지)
            
        Returns:
            번역된 텍스트. 번역 실패 시 원본 텍스트 반환
        """
        # 빈 텍스트 처리
        if not text or not text.strip():
            return text
        
        # HTML 태그 제거 및 텍스트 정리
        cleaned_text = self._clean_text(text)
        if not cleaned_text or not cleaned_text.strip():
            return text
        
        # 영어 -> 한국어 번역만 지원 (다른 언어 쌍은 필요시 확장)
        if source_lang != 'en' or target_lang != 'ko':
            self.logger.warning(
                f"지원하지 않는 언어 쌍: {source_lang} -> {target_lang}. "
                f"원본 텍스트를 그대로 반환합니다."
            )
            return text
        
        try:
            # Google Translator 인스턴스 가져오기
            translator = self._get_translator(source_lang, target_lang)
            
            # 번역 수행
            translated_text = translator.translate(cleaned_text)
            
            # 번역 결과가 비어있거나 None이면 원본 반환
            if not translated_text or not translated_text.strip():
                return text
            
            translated_text = translated_text.strip()
            
            # 원본과 동일하면 번역 실패로 간주
            if translated_text == cleaned_text:
                return text
            
            # Google Translate API rate limit 방지를 위한 짧은 지연
            # (과도한 요청 방지)
            time.sleep(0.1)
            
            return translated_text
            
        except Exception as e:
            self.logger.error(f"번역 중 오류 발생: {str(e)}", exc_info=True)
            # 오류 발생 시 원본 텍스트 반환
            return text
    
    def translate_batch(
        self,
        texts: list,
        source_lang: str = 'en',
        target_lang: str = 'ko',
        model_name: Optional[str] = None
    ) -> list:
        """
        여러 텍스트를 배치로 번역합니다.
        
        Args:
            texts: 번역할 텍스트 리스트
            source_lang: 원본 언어
            target_lang: 목표 언어
            model_name: 사용하지 않음 (호환성을 위해 유지)
            
        Returns:
            번역된 텍스트 리스트
        """
        results = []
        for text in texts:
            translated = self.translate_text(text, source_lang, target_lang, model_name)
            results.append(translated)
        return results


# 전역 번역 서비스 인스턴스
translation_service = TranslationService()
