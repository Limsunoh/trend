import { useState, useEffect } from 'react'
import { useNavigate } from 'react-router-dom'
import { analyzerAPI } from '../services/api'

const ANALYSIS_TYPES = [
  { key: 'keywords', label: '키워드 분석', api: analyzerAPI.getKeywordsAnalysis },
  { key: 'compare-platforms', label: '플랫폼 비교 분석', api: analyzerAPI.getComparePlatformsAnalysis },
  { key: 'hot-keywords', label: '인기 키워드 분석', api: analyzerAPI.getHotKeywordsAnalysis },
  { key: 'time-lag', label: '시간차 분석', api: analyzerAPI.getTimeLagAnalysis },
  { key: 'surge-keywords', label: '급상승 키워드 분석', api: analyzerAPI.getSurgeKeywordsAnalysis },
  { key: 'trend-synchronization', label: '트렌드 동기화 분석', api: analyzerAPI.getTrendSynchronizationAnalysis },
  { key: 'hourly-trends', label: '시간대별 트렌드 분석', api: analyzerAPI.getHourlyTrendsAnalysis },
  { key: 'keyword-occurrence-times', label: '키워드 등장 시간 분석', api: analyzerAPI.getKeywordOccurrenceTimesAnalysis },
  { key: 'keyword-timeline', label: '키워드 타임라인 분석', api: analyzerAPI.getKeywordTimelineAnalysis },
  { key: 'multiple-keywords-timeline', label: '다중 키워드 타임라인 분석', api: analyzerAPI.getMultipleKeywordsTimelineAnalysis },
  { key: 'engagement-keywords', label: '참여도 기반 키워드 분석', api: analyzerAPI.getEngagementKeywordsAnalysis },
]

function AnalyzerSection() {
  const navigate = useNavigate()
  const [activeAnalysis, setActiveAnalysis] = useState('keywords')
  const [data, setData] = useState([])
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState(null)
  const [filters, setFilters] = useState({
    platform: '',
    days: '',
    status: '',
  })

  useEffect(() => {
    loadData()
  }, [activeAnalysis, filters])

  const loadData = async () => {
    setLoading(true)
    setError(null)
    try {
      const analysisType = ANALYSIS_TYPES.find(t => t.key === activeAnalysis)
      if (!analysisType) return

      const params = {}
      if (filters.platform) params.platform = filters.platform
      if (filters.days) params.days = parseInt(filters.days)
      if (filters.status) params.status = filters.status
      params.lang = 'ko'

      const response = await analysisType.api(params)
      setData(response.data.results || response.data || [])
    } catch (err) {
      setError(err.message || '데이터를 불러오는 중 오류가 발생했습니다.')
    } finally {
      setLoading(false)
    }
  }

  const handleItemClick = (item) => {
    navigate(`/analysis/${item.id}`)
  }

  return (
    <div>
      <div className="section">
        <h2>분석 결과</h2>
        
        <div className="nav" style={{ flexWrap: 'wrap', marginBottom: '20px' }}>
          {ANALYSIS_TYPES.map((type) => (
            <button
              key={type.key}
              className={activeAnalysis === type.key ? 'active' : ''}
              onClick={() => setActiveAnalysis(type.key)}
            >
              {type.label}
            </button>
          ))}
        </div>

        <div className="filters">
          <select
            value={filters.platform}
            onChange={(e) => setFilters({ ...filters, platform: e.target.value })}
          >
            <option value="">전체 플랫폼</option>
            <option value="news">뉴스</option>
            <option value="sns">SNS</option>
            <option value="both">Both</option>
          </select>
          <input
            type="number"
            placeholder="분석 기간 (일수)"
            value={filters.days}
            onChange={(e) => setFilters({ ...filters, days: e.target.value })}
            style={{ width: '150px' }}
          />
          <select
            value={filters.status}
            onChange={(e) => setFilters({ ...filters, status: e.target.value })}
          >
            <option value="">전체 상태</option>
            <option value="success">성공</option>
            <option value="failed">실패</option>
          </select>
        </div>

        {error && <div className="error">{error}</div>}
        
        {loading ? (
          <div className="loading">로딩 중...</div>
        ) : (
          <>
            {data.length === 0 ? (
              <div className="loading">분석 결과가 없습니다.</div>
            ) : (
              <>
                <h3 style={{ marginBottom: '10px' }}>분석 결과 목록 (항목 클릭 시 상세 페이지로 이동)</h3>
                <table className="table table-list">
                  <thead>
                    <tr>
                      <th>ID</th>
                      <th>분석 타입</th>
                      <th>플랫폼</th>
                      <th>기간</th>
                      <th>상태</th>
                      <th>생성일</th>
                    </tr>
                  </thead>
                  <tbody>
                    {data.map((item) => (
                      <tr
                        key={item.id}
                        onClick={() => handleItemClick(item)}
                        className="clickable-row"
                      >
                        <td>{item.id}</td>
                        <td>{item.analysis_type || item.분석_타입}</td>
                        <td>{item.platform || item.플랫폼 || '-'}</td>
                        <td>{item.days != null ? `${item.days}일` : '-'}</td>
                        <td>
                          <span className={`badge ${item.status === 'success' || item.상태 === 'success' ? 'success' : 'failed'}`}>
                            {item.status || item.상태 || '-'}
                          </span>
                        </td>
                        <td>
                          {item.created_at
                            ? new Date(item.created_at).toLocaleString('ko-KR', { dateStyle: 'short', timeStyle: 'short' })
                            : (item.생성일 || '-')}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </>
            )}
          </>
        )}
      </div>
    </div>
  )
}

export default AnalyzerSection
