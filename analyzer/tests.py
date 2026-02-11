"""
형태소 분석 서비스 테스트

PyKOMORAN 설정이 제대로 되었는지 테스트합니다.
"""

from django.test import TestCase

from analyzer.services import PYKOMORAN_AVAILABLE, MorphologicalAnalyzer, get_analyzer


class MorphologicalAnalyzerTest(TestCase):
    """형태소 분석기 테스트"""

    def setUp(self):
        """테스트 전 설정"""
        if not PYKOMORAN_AVAILABLE:
            self.skipTest("PyKomoran이 설치되지 않았습니다.")

    def test_analyzer_initialization(self):
        """형태소 분석기 초기화 테스트"""
        analyzer = MorphologicalAnalyzer()
        self.assertIsNotNone(analyzer.komoran)

    def test_analyze_basic(self):
        """기본 형태소 분석 테스트"""
        analyzer = MorphologicalAnalyzer()
        text = "대한민국은 민주공화국이다."
        result = analyzer.analyze(text)

        self.assertIsInstance(result, list)
        self.assertGreater(len(result), 0)
        # 결과는 (형태소, 품사) 튜플이어야 함
        if result:
            morph, pos = result[0]
            self.assertIsInstance(morph, str)
            self.assertIsInstance(pos, str)

    def test_extract_nouns(self):
        """명사 추출 테스트"""
        analyzer = MorphologicalAnalyzer()
        text = "인공지능과 머신러닝은 미래 기술이다."
        nouns = analyzer.extract_nouns(text)

        self.assertIsInstance(nouns, list)
        # 명사가 추출되어야 함
        self.assertGreater(len(nouns), 0)

    def test_extract_keywords(self):
        """키워드 추출 테스트"""
        analyzer = MorphologicalAnalyzer()
        text = "인공지능과 머신러닝은 미래 기술이다."
        keywords = analyzer.extract_keywords(text)

        self.assertIsInstance(keywords, list)
        # 키워드가 추출되어야 함
        self.assertGreater(len(keywords), 0)

    def test_keyword_frequency(self):
        """키워드 빈도 계산 테스트"""
        analyzer = MorphologicalAnalyzer()
        texts = [
            "인공지능은 미래 기술이다.",
            "머신러닝과 인공지능은 관련이 있다.",
            "인공지능 기술이 발전하고 있다.",
        ]

        frequency = analyzer.get_keyword_frequency(texts)

        self.assertIsInstance(frequency, dict)
        # "인공지능"이 여러 번 나왔으므로 빈도가 있어야 함
        self.assertGreater(frequency.get("인공지능", 0), 0)

    def test_singleton_pattern(self):
        """싱글톤 패턴 테스트"""
        analyzer1 = get_analyzer()
        analyzer2 = get_analyzer()

        # 같은 인스턴스여야 함
        self.assertIs(analyzer1, analyzer2)

    def test_empty_text(self):
        """빈 텍스트 처리 테스트"""
        analyzer = MorphologicalAnalyzer()

        result = analyzer.analyze("")
        self.assertEqual(result, [])

        result = analyzer.analyze("   ")
        self.assertEqual(result, [])


class PyKomoranInstallationTest(TestCase):
    """PyKOMORAN 설치 확인 테스트"""

    def test_pykomoran_available(self):
        """PyKOMORAN 설치 여부 확인"""
        if not PYKOMORAN_AVAILABLE:
            self.fail(
                "PyKomoran이 설치되지 않았습니다.\n"
                "다음 명령어로 설치하세요: pip install PyKomoran\n"
                "또한 Java 8 이상이 설치되어 있어야 합니다."
            )
