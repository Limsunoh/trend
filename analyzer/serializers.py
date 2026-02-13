from rest_framework import serializers
from .models import TrendAnalysisResult


class TrendAnalysisResultSerializer(serializers.ModelSerializer):
    """트렌드 분석 결과 Serializer"""
    
    class Meta:
        model = TrendAnalysisResult
        fields = '__all__'

    def to_representation(self, instance):
        # 응답 직전에 호출되며, lang 파라미터 기준으로 한글 키 변환
        data = super().to_representation(instance)
        request = (
            self.context.get('request') if hasattr(self, 'context') else None
        )
        lang = 'ko'
        if request is not None:
            lang = request.query_params.get('lang', 'ko')
        if lang != 'ko':
            return data
        return self._translate_result_item(data)

    @classmethod
    def translate_latest_payload(cls, payload, lang='ko'):
        # 캐시에서 바로 내려가는 latest 응답에도 동일한 변환 적용
        if lang != 'ko':
            return payload
        result_data = payload.get('result_data')
        if isinstance(result_data, dict):
            payload = dict(payload)
            payload['result_data'] = cls._translate_result_data(
                payload.get('analysis_type'),
                result_data
            )
        return payload

    @classmethod
    def _translate_result_item(cls, item):
        # 결과 1건의 result_data만 타입별 변환
        analysis_type = item.get('analysis_type')
        result_data = item.get('result_data')
        if isinstance(result_data, dict):
            item = dict(item)
            item['result_data'] = cls._translate_result_data(
                analysis_type,
                result_data
            )
        return item

    @classmethod
    def _translate_result_data(cls, analysis_type, result_data):
        # 분석 타입별 전용 변환 -> 나머지는 공통 변환
        if analysis_type == 'time_lag':
            if isinstance(result_data, dict) and 'result' in result_data:
                wrapped = cls._translate_generic_result(result_data)
                inner = result_data.get('result')
                if isinstance(inner, dict):
                    wrapped['결과'] = cls._translate_time_lag_result(inner)
                return wrapped
            return cls._translate_time_lag_result(result_data)
        if analysis_type == 'surge_keywords':
            return cls._translate_surge_keywords_result(result_data)
        return cls._translate_generic_result(result_data)

    @classmethod
    def _translate_time_lag_result(cls, result):
        # 시간차 분석 전용: 구조만 유지하고 키/값 변환은 공통 매핑 사용

        translated = {}
        keywords = result.get('keywords')
        if isinstance(keywords, list):
            new_keywords = []
            for item in keywords:
                if not isinstance(item, dict):
                    continue
                new_keywords.append(cls._translate_generic_result(item))
            translated['키워드_결과'] = new_keywords

        stats = result.get('statistics')
        if isinstance(stats, dict):
            translated['통계'] = cls._translate_generic_result(stats)

        if not translated:
            return result
        return translated

    @classmethod
    def _translate_surge_keywords_result(cls, result):
        # 급상승 분석 전용: 요약/리스트 구조를 한글 키로 치환
        translated = {}
        result_block = (
            result.get('result') if isinstance(result, dict) else None
        )
        if not isinstance(result_block, dict):
            return result

        summary = result_block.get('summary')
        if isinstance(summary, dict):
            translated['요약'] = cls._translate_generic_result(summary)

        sns_items = result_block.get('sns_surge_keywords')
        if isinstance(sns_items, list):
            new_items = []
            for item in sns_items:
                if not isinstance(item, dict):
                    continue
                new_items.append(cls._translate_generic_result(item))
            translated['SNS_급상승_키워드'] = new_items

        news_items = result_block.get('news_surge_keywords')
        if isinstance(news_items, list):
            new_items = []
            for item in news_items:
                if not isinstance(item, dict):
                    continue
                new_items.append(cls._translate_generic_result(item))
            translated['뉴스_급상승_키워드'] = new_items

        if not translated:
            return result
        return translated

    @classmethod
    def _translate_generic_result(cls, result):
        # 공통 키 매핑 + 재귀 변환으로 대부분의 분석 결과 처리
        key_map = {
            'status': '상태',
            'result': '결과',
            'summary': '요약',
            'statistics': '통계',
            'keyword': '키워드',
            'keywords': '키워드_목록',
            'analyzed_keywords': '분석_키워드',
            'posts': '게시물',
            'post_id': '게시물_ID',
            'post_count': '게시물수',
            'published_at': '게시_시간',
            'news': '뉴스',
            'sns': 'SNS',
            'news_frequency': '뉴스_빈도',
            'sns_frequency': 'SNS_빈도',
            'news_absolute': '뉴스_절대빈도',
            'sns_absolute': 'SNS_절대빈도',
            'news_timeline': '뉴스_타임라인',
            'sns_timeline': 'SNS_타임라인',
            'news_hourly_trends': '뉴스_시간대_트렌드',
            'sns_hourly_trends': 'SNS_시간대_트렌드',
            'news_hours_analyzed': '뉴스_분석_시간수',
            'sns_hours_analyzed': 'SNS_분석_시간수',
            'normalized_frequency': '정규화_빈도',
            'direction': '전파방향',
            'time_lag_text': '시간차',
            'time_lag_hours': '시간차_시간',
            'time_lag_seconds': '시간차_초',
            'sns_first_occurrence': 'SNS_최초등장',
            'sns_occurrence_count': 'SNS_등장수',
            'news_first_occurrence': '뉴스_최초등장',
            'news_occurrence_count': '뉴스_등장수',
            'frequency': '빈도',
            'absolute_frequency': '절대_빈도',
            'top_keywords': '상위_키워드',
            'common_keywords': '공통_키워드',
            'news_only_keywords': '뉴스_단독_키워드',
            'sns_only_keywords': 'SNS_단독_키워드',
            'news_only_count': '뉴스_단독_개수',
            'sns_only_count': 'SNS_단독_개수',
            'news_top_keywords': '뉴스_상위_키워드',
            'sns_top_keywords': 'SNS_상위_키워드',
            'correlation': '상관계수',
            'correlation_scores': '상관계수_목록',
            'sns_sequence': 'SNS_시퀀스',
            'news_sequence': '뉴스_시퀀스',
            'avg_sns_frequency': 'SNS_평균_빈도',
            'avg_news_frequency': '뉴스_평균_빈도',
            'avg_correlation': '평균_상관계수',
            'difference': '차이',
            'news_to_sns': '뉴스→SNS',
            'sns_to_news': 'SNS→뉴스',
            'simultaneous': '동시',
            'news_only': '뉴스만',
            'sns_only': 'SNS만',
            'avg_time_lag_news_to_sns': '평균시간차_뉴스→SNS',
            'avg_time_lag_sns_to_news': '평균시간차_SNS→뉴스',
            'avg_time_lag_news_to_sns_hours': '평균시간차_뉴스→SNS_시간',
            'avg_time_lag_sns_to_news_hours': '평균시간차_SNS→뉴스_시간',
            'news_to_sns_percentage': '뉴스→SNS_비율',
            'sns_to_news_percentage': 'SNS→뉴스_비율',
            'total_keywords': '전체_키워드수',
            'total_posts': '전체_게시물수',
            'total_articles': '전체_기사수',
            'news_total_articles': '뉴스_전체_기사수',
            'sns_total_posts': 'SNS_전체_게시물수',
            'news_keywords_count': '뉴스_키워드수',
            'sns_keywords_count': 'SNS_키워드수',
            'total_news_articles': '뉴스_총_기사수',
            'total_sns_posts': 'SNS_총_게시물수',
            'total_common_keywords': '공통_키워드_총수',
            'common_keywords_count': '공통_키워드수',
            'total_count': '총_건수',
            'platform': '플랫폼',
            'days': '기간_일수',
            'min_frequency': '최소_빈도',
            'top_n': '상위_개수',
            'interval_hours': '구간_시간',
            'surge_threshold': '급상승_임계치',
            'growth_ratio': '성장비율',
            'current_count': '현재_건수',
            'previous_count': '이전_건수',
            'current_frequency': '현재_빈도',
            'previous_frequency': '이전_빈도',
            'time_bucket': '시간구간',
            'time_buckets': '시간_버킷',
            'time_buckets_count': '시간_버킷_개수',
            'timeline': '타임라인',
            'timelines': '타임라인_모음',
            'time_labels': '시간_라벨',
            'time_bucket_labels': '시간_구간_라벨',
            'common_time_labels': '공통_시간_라벨',
            'timeline_data': '타임라인_데이터',
            'occurrence_count': '등장수',
            'first_occurrence': '최초등장',
            'last_occurrence': '최종등장',
            'all_times': '전체_등장시간',
            'analyzed_at': '분석시각',
            'updated_at': '갱신시각',
            'views': '조회수',
            'likes': '좋아요',
            'comments': '댓글수',
            'shares': '공유수',
            'total_views': '총_조회수',
            'total_likes': '총_좋아요',
            'total_comments': '총_댓글수',
            'total_shares': '총_공유수',
            'avg_views': '평균_조회수',
            'avg_likes': '평균_좋아요',
            'avg_comments': '평균_댓글수',
            'avg_shares': '평균_공유수',
            'total_engagement': '총_참여도',
            'total_engagement_score': '총_참여도_점수',
            'avg_engagement_score': '평균_참여도_점수',
            'engagement_score': '참여도_점수',
            'engagement_weights': '참여도_가중치',
            'recent_post_count': '최근_게시물수',
            'recent_avg_engagement': '최근_평균_참여도',
            'top_engagement_score': '최고_참여도_점수',
            'engagement_keywords': '참여도_키워드',
            'news_surge_count': '뉴스_급상승_개수',
            'sns_surge_count': 'SNS_급상승_개수',
            'news_surge_keywords': '뉴스_급상승_키워드',
            'sns_surge_keywords': 'SNS_급상승_키워드',
            'synchronized_count': '동기화_개수',
            'desynchronized_count': '비동기_개수',
            'synchronized_keywords': '동기화_키워드',
            'desynchronized_keywords': '비동기_키워드',
            'viral_keywords': '바이럴_키워드',
            'viral_keywords_count': '바이럴_키워드_개수',
            'viral_score': '바이럴_점수'
        }
        value_map = {
            'direction': {
                'news_to_sns': '뉴스→SNS',
                'sns_to_news': 'SNS→뉴스',
                'simultaneous': '동시',
                'news_only': '뉴스만',
                'sns_only': 'SNS만',
                'not_found': '없음'
            }
        }
        return cls._translate_recursive(result, key_map, value_map)

    @classmethod
    def _translate_recursive(cls, value, key_map, value_map):
        # dict/list 내부까지 재귀적으로 키/값 치환
        if isinstance(value, dict):
            new_dict = {}
            for key, item in value.items():
                new_key = key_map.get(key, key)
                if key in value_map and isinstance(item, str):
                    item = value_map[key].get(item, item)
                new_dict[new_key] = cls._translate_recursive(
                    item, key_map, value_map
                )
            return new_dict
        if isinstance(value, list):
            return [
                cls._translate_recursive(item, key_map, value_map)
                for item in value
            ]
        return value
