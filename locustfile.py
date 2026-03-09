"""
Locust 부하 테스트: Trend Analyzer API

실행 (로컬 PC에서, 서버와 다른 머신 권장):
  pip install locust
  locust -f locustfile.py --host=http://3.37.203.226:8000

브라우저: http://localhost:8089 → 사용자 수·증가 속도 입력 후 Start
"""

import random

from locust import HttpUser, task, between


class TrendAPIUser(HttpUser):
    """대시보드·분석·QA API를 호출하는 가상 사용자"""

    wait_time = between(1, 3)  # 요청 간 1~3초 대기

    @task(10)
    def health(self):
        self.client.get("/api/health/")

    @task(8)
    def dashboard_news_list(self):
        self.client.get("/api/dashboard/news/", params={"page_size": 20})

    @task(8)
    def dashboard_social_list(self):
        self.client.get("/api/dashboard/social/", params={"page_size": 20})

    @task(5)
    def analyzer_results_list(self):
        self.client.get(
            "/api/analyzer/analysis-results/", params={"page_size": 10}
        )

    @task(3)
    def analyzer_keywords(self):
        self.client.get("/api/analyzer/analysis/keywords/")

    @task(2)
    def user_qa_history(self):
        self.client.get("/api/user_qa/history/", params={"page_size": 10})

    @task(1)
    def user_qa_query(self):
        """Q&A POST (부하 큼, 비중 낮게). CSRF 필요 시 서버 출처 허용."""
        queries = [
            "최근 트렌드 키워드 알려줘",
            "뉴스 요약해줘",
            "핫 키워드 분석 결과",
        ]
        self.client.post(
            "/api/user_qa/query/",
            json={"query": random.choice(queries)},
            headers={"Content-Type": "application/json"},
        )
