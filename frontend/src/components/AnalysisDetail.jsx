import { useState, useEffect } from 'react'
import { useParams, useNavigate } from 'react-router-dom'
import { analyzerAPI } from '../services/api'

const ANALYSIS_TYPE_LABELS = {
  keywords: '키워드 분석',
  compare_platforms: '플랫폼 비교 분석',
  hot_keywords: '인기 키워드 분석',
  time_lag: '시간차 분석',
  surge_keywords: '급상승 키워드 분석',
  trend_synchronization: '트렌드 동기화 분석',
  hourly_trends: '시간대별 트렌드 분석',
  engagement_keywords: '참여도 기반 키워드 분석',
}

/** 분석 타입별 한 줄 설명 (트렌드 동기화·시간대별만 사용) */
const ANALYSIS_TYPE_DESCRIPTIONS = {
  trend_synchronization:
    '뉴스와 SNS에서 시간대별로 키워드가 함께 움직이는지(동기화) 분석한 결과입니다. ' +
    '"동기화 정도"가 1에 가까우면 뉴스·SNS가 같은 시기에 같이 인기이고, -1에 가까우면 한쪽이 뜨면 다른 쪽은 줄어드는 반대로 움직입니다. ' +
    '"시간대별 등장 비율"은 각 시간 구간에서 그 키워드가 뉴스/SNS에 얼마나 나왔는지를 보여줍니다.',
  hourly_trends:
    '0시~23시 각 시간대별로 뉴스·SNS에서 어떤 키워드가 많이 등장했는지 보여줍니다. ' +
    '시간대(0시, 1시, …)를 펼치면 해당 시간대의 상위 키워드를 볼 수 있습니다.',
}

/** summary/result_data 키 → 한글 라벨 (모든 분석 데이터 공통) */
const KEY_TO_KOREAN = {
  summary: '요약',
  result: '결과',
  news: '뉴스',
  sns: 'SNS',
  common_keywords: '공통 키워드',
  news_only: '뉴스 전용',
  sns_only: 'SNS 전용',
  top_keywords: '상위 키워드',
  keyword: '키워드',
  frequency: '빈도',
  count: '건수',
  total: '합계',
  articles: '기사',
  posts: '게시물',
  news_total_articles: '뉴스 기사 수',
  sns_total_posts: 'SNS 게시물 수',
  news_keywords_count: '뉴스 키워드 수',
  sns_keywords_count: 'SNS 키워드 수',
  common_keywords_count: '공통 키워드 수',
  total_keywords: '총 키워드 수',
  statistics: '통계',
  avg_correlation: '평균 동기화 정도',
  correlation: '동기화 정도',
  correlation_scores: '키워드별 동기화 분석',
  news_sequence: '시간대별 뉴스 등장 비율',
  sns_sequence: '시간대별 SNS 등장 비율',
  avg_news_frequency: '뉴스에서 평균 등장 비율',
  avg_sns_frequency: 'SNS에서 평균 등장 비율',
  synchronized_count: '동기화 건수',
  desynchronized_count: '비동기화 건수',
  synchronized_keywords: '동기화된 키워드 (뉴스·SNS 같이 움직임)',
  desynchronized_keywords: '비동기화된 키워드 (한쪽에서만 주로 움직임)',
  news_surge_count: '뉴스 급상승 건수',
  sns_surge_count: 'SNS 급상승 건수',
  news_hours_analyzed: '뉴스 분석 시간대 수',
  sns_hours_analyzed: 'SNS 분석 시간대 수',
  time_buckets: '시간대 버킷 수',
  timeline_count: '타임라인 수',
  viral_keywords_count: '바이럴 키워드 수',
  occurrence_count: '등장 횟수',
  first_occurrence: '최초 등장',
  last_occurrence: '최종 등장',
  all_times: '전체 시각',
  time_labels: '시간 라벨',
  timelines: '타임라인',
  analyzed_at: '분석 시각',
  updated_at: '갱신 시각',
  news_hot_keywords: '뉴스 인기 키워드',
  sns_hot_keywords: 'SNS 인기 키워드',
  news_surge_keywords: '뉴스 급상승 키워드',
  sns_surge_keywords: 'SNS 급상승 키워드',
  news_hourly_trends: '뉴스 시간대별 트렌드',
  sns_hourly_trends: 'SNS 시간대별 트렌드',
  뉴스: '뉴스',
  SNS: 'SNS',
  뉴스_급상승_키워드: '뉴스 급상승 키워드',
  SNS_급상승_키워드: 'SNS 급상승 키워드',
  뉴스_시간대_트렌드: '뉴스 시간대별 트렌드',
  SNS_시간대_트렌드: 'SNS 시간대별 트렌드',
  상관계수_목록: '키워드별 동기화 분석 (각 키워드가 뉴스·SNS에서 얼마나 같이 움직이는지)',
  상관계수: '동기화 정도 (1에 가까우면 같은 시기에 같이 인기, -1에 가까우면 반대로 움직임)',
  뉴스_시퀀스: '시간대별 뉴스 등장 비율 (각 구간에서 뉴스에 얼마나 나왔는지)',
  SNS_시퀀스: '시간대별 SNS 등장 비율 (각 구간에서 SNS에 얼마나 나왔는지)',
  뉴스_평균_빈도: '뉴스에서 평균 등장 비율',
  SNS_평균_빈도: 'SNS에서 평균 등장 비율',
  status: '상태',
  error: '오류',
  parameters: '파라미터',
  days: '기간(일)',
  top_n: '상위 N개',
  platform: '플랫폼',
  interval_hours: '구간(시간)',
  surge_threshold: '급상승 임계값',
  min_frequency: '최소 빈도',
  engagement_weights: '참여도 가중치',
}

function labelForKey(key) {
  return KEY_TO_KOREAN[key] ?? key
}

/** 배열 인덱스 키("0","1",…) → "항목 1", "항목 2", … (hourKeys면 0~23 → "0시"~"23시") */
function displayLabelForKey(key, hourKeys = false) {
  if (/^\d+$/.test(String(key))) {
    const n = Number(key)
    if (hourKeys && n >= 0 && n <= 23) return `${n}시`
    return `항목 ${n + 1}`
  }
  return labelForKey(key)
}

/** ISO 시각 문자열 → 년월일 시 분 초 (초 뒤 .359507+00:00 제거) */
function formatDateTime(str) {
  if (typeof str !== 'string') return str
  const m = str.match(/^(\d{4})-(\d{2})-(\d{2})T(\d{2}):(\d{2}):(\d{2})/)
  if (!m) return str
  return `${m[1]}. ${Number(m[2])}. ${Number(m[3])}. ${m[4]}:${m[5]}:${m[6]}`
}

/** 숫자 표시: 0~1 소수는 퍼센트, 그 외는 보기 쉬운 형식 (아주 작은 비율도 퍼센트로 표시) */
function formatNumber(num) {
  if (Number.isInteger(num)) return String(num)
  const abs = Math.abs(num)
  if (num > 0 && num < 1) return (num * 100).toFixed(4) + '%'
  if (num > -1 && num < 0) return (num * 100).toFixed(4) + '%'
  if (abs < 1e-4 && num !== 0) return num.toExponential(2)
  return num.toLocaleString('ko-KR', { maximumFractionDigits: 4 })
}

function formatValue(value, depth = 0) {
  if (value === null || value === undefined) return '-'
  if (typeof value === 'boolean') return value ? '예' : '아니오'
  if (typeof value === 'number') return formatNumber(value)
  if (typeof value === 'string') {
    if (/^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}/.test(value)) return formatDateTime(value)
    return value
  }
  if (Array.isArray(value)) {
    if (value.length === 0) return '(없음)'
    return value.map((item, i) => {
      if (item && typeof item === 'object' && !Array.isArray(item)) {
        return <Block key={i} data={item} title={`항목 ${i + 1}`} depth={depth} />
      }
      return <div key={i} className="analysis-list-item">{formatValue(item, depth)}</div>
    })
  }
  if (typeof value === 'object') {
    return <Block data={value} depth={depth} />
  }
  return String(value)
}

/** 시퀀스(시간 구간별 비율 배열)인지 판별 */
const SEQUENCE_KEYS = new Set(['news_sequence', 'sns_sequence', '뉴스_시퀀스', 'SNS_시퀀스'])

/** 시퀀스 배열을 "1월 20일 0시~6시: 0.36%" 형태로 표시 (labels 없으면 "N번째 구간" 사용) */
function formatSequenceValue(value, depth = 0, labels = null) {
  if (!Array.isArray(value) || value.length === 0) return '(없음)'
  return (
    <div className="analysis-sequence-list">
      {value.map((v, i) => (
        <div key={i} className="analysis-list-item">
          <span className="analysis-sequence-label">
            {labels && labels[i] != null ? labels[i] : `${i + 1}번째 구간`}
          </span>: {formatValue(v, depth)}
        </div>
      ))}
    </div>
  )
}

/**
 * 객체에서 뉴스/SNS 쌍 찾기.
 * API가 lang=ko일 때 한글 키(뉴스, SNS, 뉴스_급상승_키워드, SNS_급상승_키워드 등)로 내려오므로 영문/한글 모두 처리.
 */
function findNewsSnsPairs(data) {
  if (!data || typeof data !== 'object') return []
  const keys = Object.keys(data).filter((k) => k !== 'status' && k !== '상태')
  const pairs = []

  // 영문: news / sns
  const newsKeysEn = keys.filter((k) => k.startsWith('news_') || k === 'news')
  const snsKeysEn = keys.filter((k) => k.startsWith('sns_') || k === 'sns')
  if (data.news !== undefined && data.sns !== undefined) {
    pairs.push(['news', 'sns'])
  }
  newsKeysEn.forEach((nk) => {
    if (nk === 'news') return
    const suffix = nk.replace(/^news_/, '')
    const sk = snsKeysEn.find((s) => s === 'sns_' + suffix)
    if (sk) pairs.push([nk, sk])
  })

  // 한글: 뉴스 / SNS (API serializer가 ko일 때 변환)
  const newsKeysKo = keys.filter((k) => k === '뉴스' || k.startsWith('뉴스_'))
  const snsKeysKo = keys.filter((k) => k === 'SNS' || k.startsWith('SNS_'))
  if (data['뉴스'] !== undefined && data['SNS'] !== undefined) {
    pairs.push(['뉴스', 'SNS'])
  }
  newsKeysKo.forEach((nk) => {
    if (nk === '뉴스') return
    const suffix = nk.replace(/^뉴스_/, '')
    const sk = snsKeysKo.find((s) => s === 'SNS_' + suffix)
    if (sk) pairs.push([nk, sk])
  })

  return pairs
}

/** result_data가 { result: { ... } } 또는 { 결과: { ... } } 형태면 실제 데이터는 그 안에 있음 */
function getLayoutData(data) {
  if (!data || typeof data !== 'object') return data
  const inner = data.result ?? data['결과']
  if (inner != null && typeof inner === 'object') {
    return inner
  }
  return data
}

/** 공통 키워드 먼저, 뉴스만/SNS만은 뒤로 (플랫폼 비교 등) */
const COMMON_KEYWORD_KEYS = new Set(['common_keywords', '공통_키워드', '공통키워드'])
const ONLY_KEYS = new Set(['news_only', 'sns_only', '뉴스만', 'SNS만'])
function sortOtherKeys(keys) {
  return [...keys].sort((a, b) => {
    const orderOf = (k) => COMMON_KEYWORD_KEYS.has(k) ? 0 : ONLY_KEYS.has(k) ? 2 : 1
    return orderOf(a) - orderOf(b)
  })
}

/** 분석 결과: 공통/기타는 위에, news/sns 쌍은 항상 왼쪽(뉴스) / 오른쪽(SNS) 나란히 (전체 분석 공통) */
function ResultDataLayout({ data }) {
  const layoutData = getLayoutData(data)
  const pairs = findNewsSnsPairs(layoutData)
  const pairedKeys = new Set(pairs.flat())
  const otherKeysRaw = Object.keys(layoutData).filter(
    (k) => k !== 'status' && k !== '상태' && !pairedKeys.has(k)
  )
  const otherKeys = sortOtherKeys(otherKeysRaw)
  const otherData = Object.fromEntries(otherKeys.map((k) => [k, layoutData[k]]))

  return (
    <>
      {otherKeys.length > 0 && (
        <Block data={otherData} depth={0} hideStatus />
      )}
      {pairs.map(([newsKey, snsKey]) => (
        <div key={newsKey + '-' + snsKey} className="analysis-result-two-col">
          <div className="analysis-result-col">
            <div className="analysis-block-title">{labelForKey(newsKey)}</div>
            <Block
              data={layoutData[newsKey]}
              depth={1}
              hideStatus
              hourKeys={newsKey === 'news_hourly_trends' || newsKey === 'sns_hourly_trends' || newsKey === '뉴스_시간대_트렌드' || newsKey === 'SNS_시간대_트렌드'}
            />
          </div>
          <div className="analysis-result-col">
            <div className="analysis-block-title">{labelForKey(snsKey)}</div>
            <Block
              data={layoutData[snsKey]}
              depth={1}
              hideStatus
              hourKeys={snsKey === 'news_hourly_trends' || snsKey === 'sns_hourly_trends' || snsKey === '뉴스_시간대_트렌드' || snsKey === 'SNS_시간대_트렌드'}
            />
          </div>
        </div>
      ))}
    </>
  )
}

function Block({ data, title, depth = 0, hideStatus = false, hourKeys = false }) {
  if (!data || typeof data !== 'object') return null
  let entries = Object.entries(data)
  if (hideStatus) entries = entries.filter(([key]) => key !== 'status')
  if (entries.length === 0) return <span className="analysis-empty">(비어 있음)</span>

  return (
    <div className={`analysis-block ${depth > 0 ? 'analysis-block-nested' : ''}`}>
      {title && <div className="analysis-block-title">{title}</div>}
      <dl className="analysis-dl">
        {entries.map(([key, value]) => {
          const isIndexRow = /^\d+$/.test(String(key))
          return (
          <div key={key} className={`analysis-dl-row${isIndexRow ? ' analysis-row-index' : ''}`}>
            <dt className="analysis-dt">{displayLabelForKey(key, hourKeys)}</dt>
            <dd className="analysis-dd">
              {typeof value === 'object' && value !== null && !Array.isArray(value) && Object.keys(value).length > 0 ? (
                formatValue(value, depth + 1)
              ) : Array.isArray(value) ? (
                SEQUENCE_KEYS.has(key) ? (
                  formatSequenceValue(value, depth + 1, data['시간_구간_라벨'] ?? data['time_bucket_labels'])
                ) : (
                  <div className="analysis-array">{formatValue(value, depth + 1)}</div>
                )
              ) : (
                formatValue(value, depth)
              )}
            </dd>
          </div>
          );
        })}
      </dl>
    </div>
  )
}

function AnalysisDetail() {
  const { id } = useParams()
  const navigate = useNavigate()
  const [item, setItem] = useState(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState(null)

  useEffect(() => {
    let cancelled = false
    analyzerAPI.getAnalysisResult(id)
      .then((res) => {
        if (!cancelled) setItem(res.data)
      })
      .catch((err) => {
        if (!cancelled) setError(err.message || '로딩 실패')
      })
      .finally(() => {
        if (!cancelled) setLoading(false)
      })
    return () => { cancelled = true }
  }, [id])

  if (loading) return <div className="loading">로딩 중...</div>
  if (error) return <div className="error">{error}</div>
  if (!item) return null

  const typeLabel = ANALYSIS_TYPE_LABELS[item.analysis_type] || item.analysis_type
  const createdDisplay = item.created_at
    ? new Date(item.created_at).toLocaleString('ko-KR', { dateStyle: 'medium', timeStyle: 'short' })
    : '-'

  return (
    <div className="section detail-page analysis-detail-page">
      <button type="button" className="back-btn" onClick={() => navigate(-1)}>
        ← 목록으로
      </button>
      <h2>분석 결과 상세</h2>

      <div className="detail-meta analysis-detail-meta">
        <span>ID: {item.id}</span>
        <span>분석: {typeLabel}</span>
        <span>플랫폼: {item.platform ?? '-'}</span>
        <span>기간: {item.days != null ? `${item.days}일` : '-'}</span>
        <span>
          상태:{' '}
          <span className={`badge ${item.status === 'success' ? 'success' : 'failed'}`}>
            {item.status === 'success' ? '성공' : item.status === 'failed' ? '실패' : item.status}
          </span>
        </span>
        <span>생성: {createdDisplay}</span>
      </div>

      {item.error_message && (
        <div className="analysis-error-message">
          <strong>오류 메시지</strong>
          <pre>{item.error_message}</pre>
        </div>
      )}

      <section className="analysis-detail-section">
        <h3>요약</h3>
        {item.summary && typeof item.summary === 'object' && Object.keys(item.summary).length > 0 ? (
          <Block data={item.summary} depth={0} />
        ) : (
          <p className="analysis-empty">요약 데이터가 없습니다.</p>
        )}
      </section>

      <section className="analysis-detail-section">
        <h3>분석 결과</h3>
        {ANALYSIS_TYPE_DESCRIPTIONS[item.analysis_type] && (
          <p className="analysis-type-description">{ANALYSIS_TYPE_DESCRIPTIONS[item.analysis_type]}</p>
        )}
        {item.result_data && typeof item.result_data === 'object' && Object.keys(item.result_data).length > 0 ? (
          <ResultDataLayout data={item.result_data} />
        ) : (
          <p className="analysis-empty">결과 데이터가 없습니다.</p>
        )}
      </section>

      {item.parameters && typeof item.parameters === 'object' && Object.keys(item.parameters).length > 0 && (
        <section className="analysis-detail-section analysis-params">
          <h3>분석 파라미터</h3>
          <Block data={item.parameters} depth={0} />
        </section>
      )}
    </div>
  )
}

export default AnalysisDetail
