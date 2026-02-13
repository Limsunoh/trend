import { useState, useEffect, useRef } from 'react'
import { useNavigate, useSearchParams } from 'react-router-dom'
import { dataCollectorAPI } from '../services/api'

const API_BASE = 'http://localhost:8000'
const PAGE_SIZE = 50

const NEWS_LIST_COLUMNS = [
  { key: 'source_name', label: '소스', width: 120 },
  { key: 'title_short', label: '제목', width: 'auto' },
  { key: 'published_at_display', label: '발행일', width: 140 },
  { key: 'collected_at_display', label: '수집일', width: 140 },
  { key: 'category', label: '카테고리', width: 100 },
  { key: 'thumbnail_url', label: '썸네일', width: 80 },
]

const SOCIAL_LIST_COLUMNS = [
  { key: 'source_name', label: '소스', width: 120 },
  { key: 'title_short', label: '제목', width: 'auto' },
  { key: 'published_at_display', label: '발행일', width: 140 },
  { key: 'collected_at_display', label: '수집일', width: 140 },
  { key: 'thumbnail_url', label: '썸네일', width: 80 },
]

const NEWS_SORT_OPTIONS = [
  { value: '-collected_at', label: '최신순 (수집일)' },
  { value: 'source__publisher', label: '신문사순' },
  { value: '-published_at', label: '발행일순' },
]

const SOCIAL_SORT_OPTIONS = [
  { value: '-collected_at', label: '최신순 (수집일)' },
  { value: 'source__display_name', label: '소스순' },
  { value: '-published_at', label: '발행일순' },
]

const NEWS_SEARCH_FIELDS = [
  { value: 'category', label: '카테고리' },
  { value: 'title', label: '제목' },
  { value: 'published_at', label: '발행일' },
  { value: 'collected_at', label: '수집일' },
  { value: 'source', label: '신문사' },
]

const SOCIAL_SEARCH_FIELDS = [
  { value: 'title', label: '제목' },
  { value: 'published_at', label: '발행일' },
  { value: 'collected_at', label: '수집일' },
  { value: 'source', label: '소스' },
]

function DataCollectorSection() {
  const navigate = useNavigate()
  const [searchParams, setSearchParams] = useSearchParams()
  const didRestoreFromUrl = useRef(false)

  const [activeSubTab, setActiveSubTab] = useState('news')
  const [data, setData] = useState([])
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState(null)
  const [filters, setFilters] = useState({})
  const [ordering, setOrdering] = useState('-collected_at')
  const [searchField, setSearchField] = useState('')
  const [searchValue, setSearchValue] = useState('')
  const [searchFieldDraft, setSearchFieldDraft] = useState('')
  const [searchValueDraft, setSearchValueDraft] = useState('')
  const [pagination, setPagination] = useState({
    count: 0,
    next: null,
    previous: null,
    page: 1,
  })

  // 마운트 시 URL 쿼리에서 목록 상태 복원 (뒤로가기 시 그대로 복원)
  useEffect(() => {
    if (didRestoreFromUrl.current) return
    didRestoreFromUrl.current = true
    const tab = searchParams.get('tab') || 'news'
    const orderingFromUrl = searchParams.get('ordering') || '-collected_at'
    const searchFieldFromUrl = searchParams.get('search_field') || ''
    const searchFromUrl = searchParams.get('search') || ''
    const pageFromUrl = parseInt(searchParams.get('page'), 10) || 1
    const platformFromUrl = searchParams.get('platform') || ''
    setActiveSubTab(tab === 'social' ? 'social' : 'news')
    setOrdering(orderingFromUrl)
    setSearchField(searchFieldFromUrl)
    setSearchValue(searchFromUrl)
    setSearchFieldDraft(searchFieldFromUrl)
    setSearchValueDraft(searchFromUrl)
    setPagination((prev) => ({ ...prev, page: pageFromUrl }))
    if (platformFromUrl) setFilters((f) => ({ ...f, platform: platformFromUrl }))
  }, [])

  useEffect(() => {
    loadData(pagination.page)
  }, [activeSubTab, filters, ordering, searchField, searchValue, pagination.page])

  // 목록 상태가 바뀔 때마다 URL 쿼리 갱신 (뒤로가기 시 이 URL로 복원됨)
  useEffect(() => {
    if (!didRestoreFromUrl.current) return
    const next = new URLSearchParams()
    next.set('tab', activeSubTab)
    next.set('ordering', ordering)
    if (searchField) next.set('search_field', searchField)
    if (searchValue) next.set('search', searchValue)
    if (pagination.page > 1) next.set('page', String(pagination.page))
    if (activeSubTab === 'social' && filters.platform) next.set('platform', filters.platform)
    setSearchParams(next, { replace: true })
  }, [activeSubTab, ordering, searchField, searchValue, pagination.page, filters.platform])

  // 탭 전환 시 검색 초기화
  const handleTabChange = (tab) => {
    setActiveSubTab(tab)
    setSearchField('')
    setSearchValue('')
    setSearchFieldDraft('')
    setSearchValueDraft('')
  }

  // '확인' 클릭 시에만 검색 적용
  const handleSearchConfirm = () => {
    setSearchField(searchFieldDraft)
    setSearchValue(searchValueDraft)
    setPagination((prev) => ({ ...prev, page: 1 }))
  }

  const loadData = async (page = 1) => {
    setLoading(true)
    setError(null)
    try {
      const params = {
        page,
        page_size: PAGE_SIZE,
        ordering,
        ...filters,
      }
      if (searchField && searchValue) {
        params.search_field = searchField
        params.search = searchValue
      }
      const response =
        activeSubTab === 'news'
          ? await dataCollectorAPI.getNewsArticles(params)
          : await dataCollectorAPI.getSocialPosts(params)
      const payload = response.data
      setData(payload.results ?? payload)
      setPagination({
        count: payload.count ?? (payload.results ?? payload).length,
        next: payload.next ?? null,
        previous: payload.previous ?? null,
        page,
      })
    } catch (err) {
      setError(err.message || '데이터를 불러오는 중 오류가 발생했습니다.')
    } finally {
      setLoading(false)
    }
  }

  const columns = activeSubTab === 'news' ? NEWS_LIST_COLUMNS : SOCIAL_LIST_COLUMNS
  const sortOptions = activeSubTab === 'news' ? NEWS_SORT_OPTIONS : SOCIAL_SORT_OPTIONS
  const searchFields = activeSubTab === 'news' ? NEWS_SEARCH_FIELDS : SOCIAL_SEARCH_FIELDS
  const isDateSearch = searchFieldDraft === 'published_at' || searchFieldDraft === 'collected_at'
  const totalPages = Math.ceil((pagination.count || 0) / PAGE_SIZE) || 1
  const currentPage = pagination.page || 1

  // 클릭 가능한 페이지 번호 목록 (1, 2, 3, ..., 현재 근처, ..., 마지막)
  const getPageNumbers = () => {
    if (totalPages <= 7) {
      return Array.from({ length: totalPages }, (_, i) => i + 1)
    }
    const pages = [1]
    const windowSize = 2
    const left = Math.max(2, currentPage - windowSize)
    const right = Math.min(totalPages - 1, currentPage + windowSize)
    if (left > 2) pages.push('...')
    for (let p = left; p <= right; p++) {
      if (!pages.includes(p)) pages.push(p)
    }
    if (right < totalPages - 1) pages.push('...')
    if (totalPages > 1) pages.push(totalPages)
    return pages
  }

  const renderThumb = (url) => {
    if (!url) return '-'
    const src = url.startsWith('http') ? url : `${API_BASE}${url}`
    return (
      <img
        src={src}
        alt=""
        className="list-thumb"
        onError={(e) => { e.target.style.display = 'none' }}
      />
    )
  }

  const handleRowClick = (item) => {
    if (activeSubTab === 'news') navigate(`/news/${item.id}`)
    else navigate(`/social/${item.id}`)
  }

  return (
    <div>
      <div className="section">
        <h2>데이터 수집</h2>
        <div className="nav">
          <button
            type="button"
            className={activeSubTab === 'news' ? 'active' : ''}
            onClick={() => handleTabChange('news')}
          >
            뉴스 기사
          </button>
          <button
            type="button"
            className={activeSubTab === 'social' ? 'active' : ''}
            onClick={() => handleTabChange('social')}
          >
            소셜 미디어 게시물
          </button>
        </div>

        <div className="filters">
          <label>
            정렬
            <select
              value={ordering}
              onChange={(e) => setOrdering(e.target.value)}
            >
              {sortOptions.map((opt) => (
                <option key={opt.value} value={opt.value}>
                  {opt.label}
                </option>
              ))}
            </select>
          </label>
          <label>
            검색 대상
            <select
              value={searchFieldDraft}
              onChange={(e) => {
                setSearchFieldDraft(e.target.value)
                setSearchValueDraft('')
              }}
            >
              <option value="">선택</option>
              {searchFields.map((opt) => (
                <option key={opt.value} value={opt.value}>
                  {opt.label}
                </option>
              ))}
            </select>
          </label>
          <label>
            검색어
            <input
              type={isDateSearch ? 'date' : 'text'}
              placeholder={isDateSearch ? 'YYYY-MM-DD' : '검색어 입력'}
              value={searchValueDraft}
              onChange={(e) => setSearchValueDraft(e.target.value)}
            />
          </label>
          <button
            type="button"
            className="confirm-search-btn"
            onClick={handleSearchConfirm}
          >
            확인
          </button>
          {(searchField || searchValue) && (
            <button
              type="button"
              className="reset-search-btn"
              onClick={() => {
                setSearchField('')
                setSearchValue('')
                setSearchFieldDraft('')
                setSearchValueDraft('')
                setPagination((prev) => ({ ...prev, page: 1 }))
              }}
            >
              검색 초기화
            </button>
          )}
          {activeSubTab === 'social' && (
            <select
              value={filters.platform ?? ''}
              onChange={(e) =>
                setFilters({ ...filters, platform: e.target.value || undefined })
              }
            >
              <option value="">전체 플랫폼</option>
              <option value="reddit">Reddit</option>
              <option value="dcinside">DC Inside</option>
            </select>
          )}
        </div>

        {error && <div className="error">{error}</div>}
        {loading ? (
          <div className="loading">로딩 중...</div>
        ) : data.length === 0 ? (
          <div className="loading">데이터가 없습니다. (검색 조건을 바꾸거나 위에서 검색 초기화)</div>
        ) : (
          <>
            <table className="table table-list">
              <thead>
                <tr>
                  {columns.map((col) => (
                    <th key={col.key} style={{ width: col.width }}>
                      {col.label}
                    </th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {data.map((item) => (
                  <tr
                    key={item.id}
                    onClick={() => handleRowClick(item)}
                    className="clickable-row"
                  >
                    {columns.map((col) => (
                      <td key={col.key}>
                        {col.key === 'thumbnail_url'
                          ? renderThumb(item[col.key])
                          : String(item[col.key] ?? '-')}
                      </td>
                    ))}
                  </tr>
                ))}
              </tbody>
            </table>
            <div className="pagination">
              <button
                type="button"
                disabled={!pagination.previous}
                onClick={() => setPagination((prev) => ({ ...prev, page: currentPage - 1 }))}
              >
                이전
              </button>
              <div className="pagination-numbers">
                {getPageNumbers().map((p, i) =>
                  p === '...' ? (
                    <span key={`ellipsis-${i}`} className="pagination-ellipsis">
                      ...
                    </span>
                  ) : (
                    <button
                      key={p}
                      type="button"
                      className={currentPage === p ? 'active' : ''}
                      onClick={() => setPagination((prev) => ({ ...prev, page: p }))}
                    >
                      {p}
                    </button>
                  )
                )}
              </div>
              <button
                type="button"
                disabled={!pagination.next}
                onClick={() => setPagination((prev) => ({ ...prev, page: currentPage + 1 }))}
              >
                다음
              </button>
              <span className="pagination-info">총 {pagination.count}건</span>
            </div>
          </>
        )}
      </div>
    </div>
  )
}

export default DataCollectorSection
