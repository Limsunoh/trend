"""
Locust 부하 테스트: Trend Analyzer API

실행 (로컬 PC에서, 서버와 다른 머신 권장):
  pip install locust
  locust -f locustfile.py --host=http://3.37.203.226:8000

브라우저: http://localhost:8089 → 사용자 수·증가 속도 입력 후 Start
"""

import random

from locust import HttpUser, between, task


class TrendAPIUser(HttpUser):
    """대시보드·분석·QA API를 호출하는 가상 사용자"""

    wait_time = between(1, 3)  # 요청 간 1~3초 대기

    @task(10)
    def dashboard_news_list(self):
        self.client.get("/api/dashboard/news/", params={"page_size": 20})

    @task(10)
    def dashboard_social_list(self):
        self.client.get("/api/dashboard/social/", params={"page_size": 20})

    @task(10)
    def analyzer_results_list(self):
        self.client.get("/api/analyzer/analysis-results/", params={"page_size": 10})

    @task(8)
    def analyzer_keywords(self):
        self.client.get("/api/analyzer/analysis/keywords/")

    @task(8)
    def user_qa_history(self):
        self.client.get("/api/user_qa/history/", params={"page_size": 10})

    @task(1)
    def user_qa_query(self):
        """Q&A POST (부하 큼, 비중 낮게). CSRF 필요 시 서버 출처 허용."""
        queries = [
            # 트렌드·키워드
            "최근 트렌드 키워드 알려줘",
            "핫 키워드 분석 결과",
            "이번 주 가장 많이 언급된 키워드는?",
            "급상승 키워드 목록 보여줘",
            "가장 많이 나온 단어 Top 10",
            "주요 이슈 키워드 정리해줘",
            "키워드 상관관계 분석",
            "트렌드 예측 가능해?",
            "지금 뜨고 있는 키워드가 뭐야?",
            "어제 대비 오늘 키워드 변화",
            "장기 트렌드 vs 단기 트렌드",
            # 뉴스
            "뉴스 요약해줘",
            "뉴스 기사 요약 5개만",
            "최근 24시간 뉴스 트렌드",
            "최근 수집된 뉴스 제목만",
            "뉴스에서 자주 나오는 주제",
            "오늘 뉴스 헤드라인만",
            "뉴스와 SNS에서 공통으로 뜨는 주제가 뭐야?",
            # 소셜·SNS
            "소셜 미디어에서 인기 있는 주제",
            "SNS 인기 게시물 주제",
            "레딧이랑 디시 비교해서 트렌드",
            "소셜 반응 많은 이슈",
            # 분석·비교·시간
            "시간대별 트렌드 변화 분석해줘",
            "플랫폼별 키워드 비교해줘",
            "트렌드 동기화 분석 결과",
            "엔지니어링 키워드 분석",
            "시간차 분석 결과 알려줘",
            "비교 플랫폼 분석",
            "시간대별 트렌드 요약",
            "뉴스랑 SNS 중 어디가 먼저 터졌어?",
            "어떤 플랫폼이 트렌드 반영이 빨라?",
            # 요약·현황
            "분석 결과 요약해줘",
            "데이터 수집 현황 알려줘",
            "전체 트렌드 한 줄로 요약",
            "지금까지 분석한 결과 요약",
            "수집된 데이터 규모가 어느 정도야?",
            # 질의 형태 다양화
            "트렌드 동기화가 뭔지 설명해줘",
            "급상승 키워드 기준이 뭐야?",
            "분석에 쓰는 데이터 출처는?",
            "최근 일주일 트렌드 요약해줘",
            "주요 키워드 3개만 뽑아줘",
            "뉴스 없이 SNS만 있는 이슈 있어?",
            "반대로 SNS 없이 뉴스만 있는 건?",
            # 자연스러운·일상적인 질문
            "요즘 뭐가 잘 나가?",
            "지금 사람들 관심사가 뭐야?",
            "오늘 뭐가 핫해?",
            "요즘 뉴스에서 자주 나오는 거 뭐 있어?",
            "SNS에서 요즘 뭐가 많이 오르내려?",
            "뭔가 요약해서 알려줘",
            "대충 요즘 트렌드만 알려줘",
            "한번 정리해줘 뭐가 중요한지",
            "요즘 이슈 되게 많지? 뭐가 제일 컸어?",
            "레딧이랑 디시에서 말하는 거 비슷해?",
            "뉴스 먼저 나오고 SNS 터지는 거야? 반대야?",
            "그거 어떻게 알아? 데이터 어디서 가져와?",
            "믿어도 돼? 출처가 어디야?",
            "이거 진짜야? 근거 있어?",
            "더 자세히 알려줘",
            "그래서 결론이 뭐야?",
            "요즘 트렌드 한마디로 하면?",
            "뭐가 중요해 지금?",
            "나 요즘 놓친 거 있어?",
            "오늘 아침에 뭐가 터졌어?",
            "이번 주 가장 말 많았던 거",
            "사람들 반응 많은 거 위주로",
            "재밌는 이슈 있어?",
            "심각한 거랑 가벼운 거 구분해서",
        ]
        self.client.post(
            "/api/user_qa/query/",
            json={"query": random.choice(queries)},
            headers={"Content-Type": "application/json"},
        )
