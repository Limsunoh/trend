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
  keyword_occurrence_times: '키워드 등장 시간 분석',
  keyword_timeline: '키워드 타임라인 분석',
  multiple_keywords_timeline: '다중 키워드 타임라인 분석',
  engagement_keywords: '참여도 기반 키워드 분석',
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
  avg_correlation: '평균 상관관계',
  synchronized_count: '동기화 건수',
  desynchronized_count: '비동기화 건수',
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

/** 배열 인덱스 키("0","1",…) → "항목 1", "항목 2", … */
function displayLabelForKey(key) {
  if (/^\d+$/.test(String(key))) return `항목 ${Number(key) + 1}`
  return labelForKey(key)
}

/** ISO 시각 문자열 → 년월일 시 분 초 (초 뒤 .359507+00:00 제거) */
function formatDateTime(str) {
  if (typeof str !== 'string') return str
  const m = str.match(/^(\d{4})-(\d{2})-(\d{2})T(\d{2}):(\d{2}):(\d{2})/)
  if (!m) return str
  return `${m[1]}. ${Number(m[2])}. ${Number(m[3])}. ${m[4]}:${m[5]}:${m[6]}`
}

/** 숫자 표시: 0~1 소수는 퍼센트, 그 외는 보기 쉬운 형식 */
function formatNumber(num) {
  if (Number.isInteger(num)) return String(num)
  const abs = Math.abs(num)
  if (abs < 1e-4 && num !== 0) return num.toExponential(2)
  if (num > 0 && num < 1) return (num * 100).toFixed(2) + '%'
  if (num > -1 && num < 0) return (num * 100).toFixed(2) + '%'
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

/** 분석 결과: 공통/기타는 위에, news 왼쪽 / sns 오른쪽 나란히 */
function ResultDataLayout({ data }) {
  const newsKey = data.news_hot_keywords !== undefined ? 'news_hot_keywords' : (data.news !== undefined ? 'news' : null)
  const snsKey = data.sns_hot_keywords !== undefined ? 'sns_hot_keywords' : (data.sns !== undefined ? 'sns' : null)
  const sideBySideKeys = [newsKey, snsKey].filter(Boolean)
  const otherKeys = Object.keys(data).filter(
    (k) => k !== 'status' && !sideBySideKeys.includes(k)
  )
  const otherData = Object.fromEntries(otherKeys.map((k) => [k, data[k]]))

  return (
    <>
      {otherKeys.length > 0 && (
        <Block data={otherData} depth={0} hideStatus />
      )}
      {sideBySideKeys.length === 2 && (
        <div className="analysis-result-two-col">
          <div className="analysis-result-col">
            <div className="analysis-block-title">{labelForKey(newsKey)}</div>
            <Block data={data[newsKey]} depth={1} hideStatus />
          </div>
          <div className="analysis-result-col">
            <div className="analysis-block-title">{labelForKey(snsKey)}</div>
            <Block data={data[snsKey]} depth={1} hideStatus />
          </div>
        </div>
      )}
      {sideBySideKeys.length === 1 && (
        <Block data={{ [sideBySideKeys[0]]: data[sideBySideKeys[0]] }} depth={0} hideStatus />
      )}
    </>
  )
}

function Block({ data, title, depth = 0, hideStatus = false }) {
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
            <dt className="analysis-dt">{displayLabelForKey(key)}</dt>
            <dd className="analysis-dd">
              {typeof value === 'object' && value !== null && !Array.isArray(value) && Object.keys(value).length > 0 ? (
                formatValue(value, depth + 1)
              ) : Array.isArray(value) ? (
                <div className="analysis-array">{formatValue(value, depth + 1)}</div>
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
