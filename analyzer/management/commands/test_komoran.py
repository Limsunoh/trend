"""
PyKOMORAN 설정 테스트 명령어

사용법:
    python manage.py test_komoran
"""
from django.core.management.base import BaseCommand
from analyzer.services import MorphologicalAnalyzer, PYKOMORAN_AVAILABLE


class Command(BaseCommand):
    help = 'PyKOMORAN 형태소 분석기 설정을 테스트합니다.'

    def add_arguments(self, parser):
        """명령어 인자 추가"""
        parser.add_argument(
            '--java-path',
            type=str,
            help='Java 실행 파일 경로 (예: C:\\Program Files\\Java\\jdk-11\\bin\\java.exe)',
        )

    def handle(self, *args, **options):
        """명령어 실행"""
        self.stdout.write("=" * 60)
        self.stdout.write(self.style.SUCCESS("PyKOMORAN 설정 테스트"))
        self.stdout.write("=" * 60)
        
        # 1. 설치 확인
        self.stdout.write("\n[1] PyKOMORAN 설치 확인...")
        if not PYKOMORAN_AVAILABLE:
            self.stdout.write(
                self.style.ERROR(
                    "❌ PyKomoran이 설치되지 않았습니다.\n"
                    "다음 명령어로 설치하세요:\n"
                    "  pip install PyKomoran\n"
                    "또한 Java 8 이상이 설치되어 있어야 합니다."
                )
            )
            return
        
        self.stdout.write(self.style.SUCCESS("✅ PyKomoran 설치 확인됨"))
        
        # 2. 초기화 테스트
        self.stdout.write("\n[2] 형태소 분석기 초기화...")
        java_path = options.get('java_path')
        try:
            analyzer = MorphologicalAnalyzer(model_type="STABLE", java_path=java_path)
            self.stdout.write(self.style.SUCCESS("✅ PyKOMORAN 형태소 분석기 초기화 성공"))
        except Exception as e:
            error_msg = str(e)
            if "WinError 2" in error_msg or "파일을 찾을 수 없습니다" in error_msg:
                self.stdout.write(
                    self.style.ERROR(
                        f"❌ 초기화 실패: Java를 찾을 수 없습니다.\n"
                        f"   에러: {error_msg}\n\n"
                        f"해결 방법:\n"
                        f"1. Java가 설치되어 있는지 확인: java -version\n"
                        f"2. Java가 PATH에 있는지 확인\n"
                        f"3. 또는 --java-path 옵션으로 Java 경로 지정:\n"
                        f"   python manage.py test_komoran --java-path \"C:\\Program Files\\Java\\jdk-11\\bin\\java.exe\""
                    )
                )
            else:
                self.stdout.write(
                    self.style.ERROR(f"❌ 초기화 실패: {error_msg}")
                )
            return
        
        # 3. 기본 분석 테스트
        self.stdout.write("\n[3] 기본 형태소 분석 테스트...")
        test_text = "대한민국은 민주공화국이다."
        try:
            result = analyzer.analyze(test_text)
            self.stdout.write(f"   입력: {test_text}")
            self.stdout.write(f"   결과: {result}")
            self.stdout.write(self.style.SUCCESS("✅ 형태소 분석 성공"))
        except Exception as e:
            self.stdout.write(
                self.style.ERROR(f"❌ 분석 실패: {str(e)}")
            )
            return
        
        # 4. 명사 추출 테스트
        self.stdout.write("\n[4] 명사 추출 테스트...")
        test_text = "인공지능과 머신러닝은 미래 기술이다."
        try:
            nouns = analyzer.extract_nouns(test_text)
            self.stdout.write(f"   입력: {test_text}")
            self.stdout.write(f"   추출된 명사: {nouns}")
            self.stdout.write(self.style.SUCCESS("✅ 명사 추출 성공"))
        except Exception as e:
            self.stdout.write(
                self.style.ERROR(f"❌ 명사 추출 실패: {str(e)}")
            )
            return
        
        # 5. 키워드 추출 테스트
        self.stdout.write("\n[5] 키워드 추출 테스트...")
        test_text = "인공지능과 머신러닝은 미래 기술이다."
        try:
            keywords = analyzer.extract_keywords(test_text)
            self.stdout.write(f"   입력: {test_text}")
            self.stdout.write(f"   추출된 키워드: {keywords}")
            self.stdout.write(self.style.SUCCESS("✅ 키워드 추출 성공"))
        except Exception as e:
            self.stdout.write(
                self.style.ERROR(f"❌ 키워드 추출 실패: {str(e)}")
            )
            return
        
        # 6. 빈도 계산 테스트
        self.stdout.write("\n[6] 키워드 빈도 계산 테스트...")
        test_texts = [
            "인공지능은 미래 기술이다.",
            "머신러닝과 인공지능은 관련이 있다.",
            "인공지능 기술이 발전하고 있다.",
            "아이 시발 진짜 다 뒤지게 패고싶네 개새끼들",
            "섹스 좋다 섹스 좋다 섹스 좋다",
            "야르 병신 장애인"
        ]
        try:
            frequency = analyzer.get_keyword_frequency(test_texts)
            self.stdout.write("   입력 텍스트:")
            for text in test_texts:
                self.stdout.write(f"     - {text}")
            self.stdout.write(f"   키워드 빈도 (절대): {frequency}")
            self.stdout.write(self.style.SUCCESS("✅ 빈도 계산 성공"))
        except Exception as e:
            self.stdout.write(
                self.style.ERROR(f"❌ 빈도 계산 실패: {str(e)}")
            )
            return
        
        # 7. 정규화 테스트
        self.stdout.write("\n[7] 정규화 (상대 빈도) 테스트...")
        try:
            # 절대 빈도
            absolute_freq = analyzer.get_keyword_frequency(test_texts)
            
            # 정규화 (상대 빈도)
            normalized_freq = analyzer.normalize_frequency(absolute_freq)
            
            self.stdout.write("   절대 빈도 예시:")
            sample_abs = dict(list(absolute_freq.items())[:5])
            for word, count in sample_abs.items():
                self.stdout.write(f"     - {word}: {count}번")
            
            self.stdout.write("   상대 빈도 예시:")
            sample_norm = dict(list(normalized_freq.items())[:5])
            for word, ratio in sample_norm.items():
                self.stdout.write(f"     - {word}: {ratio:.4f} ({ratio*100:.2f}%)")
            
            # 검증: 상대 빈도의 합이 1.0에 가까운지 확인
            total_ratio = sum(normalized_freq.values())
            if abs(total_ratio - 1.0) < 0.0001:
                self.stdout.write(
                    f"   검증: 상대 빈도 합계 = {total_ratio:.6f} (정상)"
                )
            else:
                self.stdout.write(
                    self.style.WARNING(
                        f"   검증: 상대 빈도 합계 = {total_ratio:.6f} "
                        f"(예상: 1.0, 차이: {abs(total_ratio - 1.0):.6f})"
                    )
                )
            
            self.stdout.write(self.style.SUCCESS("✅ 정규화 성공"))
        except Exception as e:
            self.stdout.write(
                self.style.ERROR(f"❌ 정규화 실패: {str(e)}")
            )
            return
        
        # 8. 크로스 플랫폼 비교 테스트
        self.stdout.write("\n[8] 크로스 플랫폼 비교 테스트...")
        try:
            # 뉴스 텍스트 (많은 데이터)
            news_texts = [
                "인공지능은 미래 기술이다.",
                "머신러닝과 인공지능은 관련이 있다.",
                "인공지능 기술이 발전하고 있다.",
                "경제 성장과 기술 발전이 중요하다.",
                "정부는 인공지능 정책을 발표했다."
            ]
            
            # SNS 텍스트 (적은 데이터)
            sns_texts = [
                "인공지능 대박",
                "AI 최고"
            ]
            
            # 각 플랫폼별 키워드 빈도 계산
            news_freq = analyzer.get_keyword_frequency(news_texts)
            sns_freq = analyzer.get_keyword_frequency(sns_texts)
            
            # 정규화
            news_norm = analyzer.normalize_frequency(news_freq)
            sns_norm = analyzer.normalize_frequency(sns_freq)
            
            self.stdout.write("   뉴스 키워드 (절대 빈도):")
            for word, count in list(news_freq.items())[:5]:
                self.stdout.write(f"     - {word}: {count}번")
            
            self.stdout.write("   뉴스 키워드 (상대 빈도):")
            for word, ratio in list(news_norm.items())[:5]:
                self.stdout.write(f"     - {word}: {ratio:.4f} ({ratio*100:.2f}%)")
            
            self.stdout.write("   SNS 키워드 (절대 빈도):")
            for word, count in sns_freq.items():
                self.stdout.write(f"     - {word}: {count}번")
            
            self.stdout.write("   SNS 키워드 (상대 빈도):")
            for word, ratio in sns_norm.items():
                self.stdout.write(f"     - {word}: {ratio:.4f} ({ratio*100:.2f}%)")
            
            # 공통 키워드 비교
            common_keywords = set(news_norm.keys()) & set(sns_norm.keys())
            if common_keywords:
                self.stdout.write("   공통 키워드 비교:")
                for keyword in list(common_keywords)[:3]:
                    news_ratio = news_norm.get(keyword, 0)
                    sns_ratio = sns_norm.get(keyword, 0)
                    self.stdout.write(
                        f"     - {keyword}: "
                        f"뉴스 {news_ratio:.4f} ({news_ratio*100:.2f}%), "
                        f"SNS {sns_ratio:.4f} ({sns_ratio*100:.2f}%)"
                    )
            
            self.stdout.write(self.style.SUCCESS("✅ 크로스 플랫폼 비교 성공"))
        except Exception as e:
            self.stdout.write(
                self.style.ERROR(f"❌ 크로스 플랫폼 비교 실패: {str(e)}")
            )
            return
        
        # 완료
        self.stdout.write("\n" + "=" * 60)
        self.stdout.write(self.style.SUCCESS("✅ 모든 테스트 통과!"))
        self.stdout.write("=" * 60)
        self.stdout.write(
            "\n이제 analyzer.services의 MorphologicalAnalyzer를 사용할 수 있습니다.\n"
            "기본적으로 STABLE 모델을 사용하며, 더 정확한 분석이 필요하면 EXP 모델을 사용할 수 있습니다.\n"
            "정규화 기능을 사용하여 플랫폼별 키워드를 비교할 수 있습니다."
        )

