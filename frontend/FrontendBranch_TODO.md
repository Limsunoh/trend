# frontend 브랜치에서 다시 할 작업 (기억용)

analyzer 브랜치에서는 프론트 변경을 되돌려 두었습니다.
**frontend 브랜치로 넘어간 뒤** 아래 작업을 다시 적용하세요.

---

## 1. 뉴스/SNS 양쪽 배치 (모든 분석 타입)

- **파일**: `frontend/src/components/AnalysisDetail.jsx`
- **내용**:
  - `findNewsSnsPairs(data)` 추가: `result_data`에서 `news_*` / `sns_*` 쌍 찾기 (같은 suffix: `news_hourly_trends` ↔ `sns_hourly_trends` 등).
  - `ResultDataLayout`을 **쌍 단위**로 변경: `news_hot_keywords`/`sns_hot_keywords`뿐 아니라 `news_hourly_trends`/`sns_hourly_trends`, `news`/`sns` 등 모든 쌍을 왼쪽(뉴스) / 오른쪽(SNS) 두 칸으로 표시.
  - `KEY_TO_KOREAN`에 `news_hourly_trends`, `sns_hourly_trends` 추가.

---

## 2. 트렌드 동기화 / 시간대별 트렌드 분석 설명 + 시간대 라벨

- **파일**: `frontend/src/components/AnalysisDetail.jsx`
- **내용**:
  - `ANALYSIS_TYPE_DESCRIPTIONS` 추가:
    - **트렌드 동기화**: "뉴스와 SNS에서 시간대별로 키워드가 함께 움직이는지(동기화) 분석한 결과입니다. 동기화된 키워드 = 두 플랫폼에서 비슷한 시기에 인기, 비동기화 = 한쪽에서만 주로 등장."
    - **시간대별 트렌드**: "0시~23시 각 시간대별로 뉴스·SNS에서 어떤 키워드가 많이 등장했는지 보여줍니다. 시간대(0시, 1시, …)를 펼치면 해당 시간대의 상위 키워드를 볼 수 있습니다."
  - 분석 결과 섹션 상단에 위 설명 문구 표시 (`analysis-type-description`).
  - `displayLabelForKey(key, hourKeys)`: `hourKeys`일 때 0~23 → "0시"~"23시".
  - `Block`에 `hourKeys` prop 전달 (뉴스/ SNS 시간대별 트렌드 블록만).
- **파일**: `frontend/src/index.css`
- **내용**: `.analysis-type-description` 스타일 추가 (파란 배경, 왼쪽 테두리).

---

## 3. 세 가지 분석 타입 탭·API 제거 (프론트만)

- **파일**: `frontend/src/components/AnalyzerSection.jsx`
  - 탭 3개 제거: 키워드 등장 시간, 키워드 타임라인, 다중 키워드 타임라인.
- **파일**: `frontend/src/services/api.js`
  - API 3개 제거: `getKeywordOccurrenceTimesAnalysis`, `getKeywordTimelineAnalysis`, `getMultipleKeywordsTimelineAnalysis`.
- **파일**: `frontend/src/components/AnalysisDetail.jsx`
  - `ANALYSIS_TYPE_LABELS`에서 `keyword_occurrence_times`, `keyword_timeline`, `multiple_keywords_timeline` 제거 (백엔드에서 이미 제거됨).

---

이 파일은 frontend 브랜치 작업 후 삭제해도 됩니다.
