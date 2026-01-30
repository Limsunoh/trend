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

function formatValue(value, depth = 0) {
  if (value === null || value === undefined) return '-'
  if (typeof value === 'boolean') return value ? '예' : '아니오'
  if (typeof value === 'number') return String(value)
  if (typeof value === 'string') return value
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

function Block({ data, title, depth = 0 }) {
  if (!data || typeof data !== 'object') return null
  const entries = Object.entries(data)
  if (entries.length === 0) return <span className="analysis-empty">(비어 있음)</span>

  return (
    <div className={`analysis-block ${depth > 0 ? 'analysis-block-nested' : ''}`}>
      {title && <div className="analysis-block-title">{title}</div>}
      <dl className="analysis-dl">
        {entries.map(([key, value]) => (
          <div key={key} className="analysis-dl-row">
            <dt className="analysis-dt">{key}</dt>
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
        ))}
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
        <h3>요약 (summary)</h3>
        {item.summary && typeof item.summary === 'object' && Object.keys(item.summary).length > 0 ? (
          <Block data={item.summary} depth={0} />
        ) : (
          <p className="analysis-empty">요약 데이터가 없습니다.</p>
        )}
      </section>

      <section className="analysis-detail-section">
        <h3>분석 결과 (result_data)</h3>
        {item.result_data && typeof item.result_data === 'object' && Object.keys(item.result_data).length > 0 ? (
          <Block data={item.result_data} depth={0} />
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
