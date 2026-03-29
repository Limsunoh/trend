// 실행 예시:
// k6 run -e BASE_URL=http://3.37.203.226:8000 -e RATE=300 -e DURATION=3m k6_trend_api.js
// 참고: RATE는 초당 시작할 iteration 수(요청 수와 유사), DURATION은 총 테스트 시간.
import http from "k6/http";
import { check, sleep } from "k6";

const BASE_URL = __ENV.BASE_URL || "http://3.37.203.226:8000";

// Locust 비중 그대로 (user_qa_query는 0으로 제외)
// dashboard_news_list: 10
// dashboard_social_list: 10
// analyzer_results_list: 10
// analyzer_keywords: 8
// user_qa_history: 8
const TASKS = [
  { name: "dashboard_news_list", weight: 10, method: "GET", path: "/api/dashboard/news/?page_size=20" },
  { name: "dashboard_social_list", weight: 10, method: "GET", path: "/api/dashboard/social/?page_size=20" },
  { name: "analyzer_results_list", weight: 10, method: "GET", path: "/api/analyzer/analysis-results/?page_size=10" },
  { name: "analyzer_keywords", weight: 8, method: "GET", path: "/api/analyzer/analysis/keywords/" },
  { name: "user_qa_history", weight: 8, method: "GET", path: "/api/user_qa/history/?page_size=10" },
];

const TOTAL_WEIGHT = TASKS.reduce((sum, t) => sum + t.weight, 0);

function pickWeightedTask() {
  const r = Math.random() * TOTAL_WEIGHT;
  let acc = 0;
  for (const t of TASKS) {
    acc += t.weight;
    if (r <= acc) return t;
  }
  return TASKS[TASKS.length - 1];
}

export const options = {
  scenarios: {
    trend_weighted_fixed_rps: {
      // --- executor 종류 (k6는 "초당 N건" 말고도 다른 부하 모델을 쓸 수 있음) ---
      // · constant-arrival-rate (아래에서 사용): timeUnit당 반복(iteration) 시작 횟수를 고정.
      //   → Locust의 "고정 RPS"에 가깝고, 서버가 감당할 처리량(목표 TPS/RPS)을 정할 때 유리.
      // · constant-vus: VU(가상 사용자) 수만 고정. 각 VU가 default 함수를 끝까지 돌린 뒤 바로 다시 시작.
      //   → "동시 접속 N명" 시뮬에 가깝고, 응답이 느리면 실제 초당 요청 수는 자동으로 줄어듦.
      // · ramping-vus: 단계(stages)마다 VU를 서서히 늘리거나 줄임 (스모크·스트레스·한계 찾기).
      // · ramping-arrival-rate: 도착률을 단계적으로 올리거나 내림 (목표 RPS를 점진적으로 변경).
      // · per-vu-iterations: VU마다 정확히 N번만 실행 (재현 가능한 고정 건수 테스트).
      // · shared-iterations: 전체 VU가 총 N번을 나눠 실행 (총 요청 수 고정).
      // Locust(동시 사용자·wait_time)와 비슷하게 맞추려면 보통 constant-vus 또는 ramping-vus를 쓰는 편.
      //
      // 도착률(Arrival Rate) 기반 실행기 — "동시 사용자 수"가 아니라 timeUnit당 몇 번 iteration을
      // 시작할지로 부하를 맞춤 (rate + timeUnit 조합).
      executor: "constant-arrival-rate",

      // [가장 중요] 목표 초당 요청 수(RPS/TPS 유사 개념)
      // 값을 올리면 처리량 압박 증가, 보통 응답시간/실패율도 함께 상승할 수 있음
      // 예) RATE=300 -> 초당 300요청 시도
      rate: Number(__ENV.RATE || 1000),

      // rate의 단위 시간. 기본 1초이므로 rate=300이면 "1초당 300"
      // 10s로 바꾸면 rate=300은 "10초당 300(=초당 30)"이 됨
      timeUnit: "1s",

      // 테스트 총 실행 시간
      // 값을 늘리면 워밍 이후 안정 구간/메모리 누수/장기 스파이크 관찰에 유리
      // 예) 3m, 10m, 1h
      duration: __ENV.DURATION || "3m",

      // 시작 시 미리 확보할 VU(가상 유저) 수
      // 너무 작으면 목표 rate를 못 따라가며 dropped_iterations가 생길 수 있음
      // 너무 크면 부하 생성기(내 PC) 자원 사용이 커짐
      preAllocatedVUs: Number(__ENV.PRE_VUS || 700),

      // 최대 VU 상한
      // 목표 rate를 맞추기 위해 필요 시 여기까지 자동 확장
      // preAllocatedVUs < maxVUs 권장
      maxVUs: Number(__ENV.MAX_VUS || 1500),
    },
  },
  thresholds: {
    // 실패율 기준: 전체 요청 중 실패 비율이 1% 미만이어야 통과
    // 더 엄격하게 보려면 rate<0.001 (0.1%) 등으로 조정
    http_req_failed: ["rate<0.01"],

    // 지연 기준: p95가 2000ms 미만이어야 통과
    // 서비스 목표에 맞춰 500ms, 1000ms 등으로 강화 가능
    http_req_duration: ["p(95)<2000"],
  },
};

export default function () {
  const task = pickWeightedTask();
  const url = `${BASE_URL}${task.path}`;

  const res = http.get(url, {
    tags: { endpoint: task.name },
  });

  check(res, {
    "status is 2xx/3xx": (r) => r.status >= 200 && r.status < 400,
  });

  // Locust wait_time=between(1,3)와 유사한 페이싱(도착률 모드에서도 각 VU 루프 간 간격 보정용)
  sleep(1 + Math.random() * 2);
}

