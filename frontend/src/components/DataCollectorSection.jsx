import { useState, useEffect } from 'react'
import { dataCollectorAPI } from '../services/api'

function DataCollectorSection() {
  const [activeSubTab, setActiveSubTab] = useState('sources')
  const [data, setData] = useState([])
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState(null)
  const [filters, setFilters] = useState({})

  useEffect(() => {
    loadData()
  }, [activeSubTab, filters])

  const loadData = async () => {
    setLoading(true)
    setError(null)
    try {
      let response
      switch (activeSubTab) {
        case 'sources':
          response = await dataCollectorAPI.getNewsSources(filters)
          break
        case 'news':
          response = await dataCollectorAPI.getNewsArticles(filters)
          break
        case 'social':
          response = await dataCollectorAPI.getSocialPosts(filters)
          break
        case 'social-sources':
          response = await dataCollectorAPI.getSocialSources(filters)
          break
        default:
          return
      }
      setData(response.data.results || response.data)
    } catch (err) {
      setError(err.message || '데이터를 불러오는 중 오류가 발생했습니다.')
    } finally {
      setLoading(false)
    }
  }

  const renderTable = () => {
    if (data.length === 0) {
      return <div className="loading">데이터가 없습니다.</div>
    }

    const keys = Object.keys(data[0])
    return (
      <table className="table">
        <thead>
          <tr>
            {keys.map((key) => (
              <th key={key}>{key}</th>
            ))}
          </tr>
        </thead>
        <tbody>
          {data.map((item, idx) => (
            <tr key={item.id || idx}>
              {keys.map((key) => (
                <td key={key}>
                  {typeof item[key] === 'object' ? (
                    <pre style={{ fontSize: '11px', maxWidth: '300px', overflow: 'auto' }}>
                      {JSON.stringify(item[key], null, 2)}
                    </pre>
                  ) : (
                    String(item[key] || '-')
                  )}
                </td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
    )
  }

  return (
    <div>
      <div className="section">
        <h2>데이터 수집</h2>
        <div className="nav">
          <button
            className={activeSubTab === 'sources' ? 'active' : ''}
            onClick={() => setActiveSubTab('sources')}
          >
            뉴스 소스
          </button>
          <button
            className={activeSubTab === 'news' ? 'active' : ''}
            onClick={() => setActiveSubTab('news')}
          >
            뉴스 기사
          </button>
          <button
            className={activeSubTab === 'social' ? 'active' : ''}
            onClick={() => setActiveSubTab('social')}
          >
            소셜 미디어 게시물
          </button>
          <button
            className={activeSubTab === 'social-sources' ? 'active' : ''}
            onClick={() => setActiveSubTab('social-sources')}
          >
            소셜 미디어 소스
          </button>
        </div>

        {activeSubTab === 'sources' && (
          <div className="filters">
            <select
              value={filters.is_active || ''}
              onChange={(e) => setFilters({ ...filters, is_active: e.target.value || undefined })}
            >
              <option value="">전체</option>
              <option value="true">활성</option>
              <option value="false">비활성</option>
            </select>
          </div>
        )}

        {activeSubTab === 'news' && (
          <div className="filters">
            <input
              type="text"
              placeholder="제목 검색"
              value={filters.search || ''}
              onChange={(e) => setFilters({ ...filters, search: e.target.value || undefined })}
            />
            <select
              value={filters.is_processed || ''}
              onChange={(e) => setFilters({ ...filters, is_processed: e.target.value || undefined })}
            >
              <option value="">전체</option>
              <option value="true">처리됨</option>
              <option value="false">미처리</option>
            </select>
          </div>
        )}

        {activeSubTab === 'social' && (
          <div className="filters">
            <select
              value={filters.platform || ''}
              onChange={(e) => setFilters({ ...filters, platform: e.target.value || undefined })}
            >
              <option value="">전체 플랫폼</option>
              <option value="reddit">Reddit</option>
              <option value="dcinside">DC Inside</option>
            </select>
          </div>
        )}

        {error && <div className="error">{error}</div>}
        {loading ? (
          <div className="loading">로딩 중...</div>
        ) : (
          renderTable()
        )}
      </div>
    </div>
  )
}

export default DataCollectorSection
