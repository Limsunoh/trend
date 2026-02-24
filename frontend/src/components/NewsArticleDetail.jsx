import { useState, useEffect } from 'react'
import { useParams, useNavigate } from 'react-router-dom'
import { dataCollectorAPI } from '../services/api'
import { API_BASE } from '../config'

function NewsArticleDetail() {
  const { id } = useParams()
  const navigate = useNavigate()
  const [item, setItem] = useState(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState(null)

  useEffect(() => {
    let cancelled = false
    dataCollectorAPI.getNewsArticle(id)
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

  const thumbSrc = item?.thumbnail_url?.startsWith('http')
    ? item.thumbnail_url
    : item?.thumbnail_url
      ? `${API_BASE}${item.thumbnail_url}`
      : null

  if (loading) return <div className="loading">로딩 중...</div>
  if (error) return <div className="error">{error}</div>
  if (!item) return null

  return (
    <div className="section detail-page">
      <button type="button" className="back-btn" onClick={() => navigate(-1)}>
        ← 목록으로
      </button>
      <h2>뉴스 기사 상세</h2>
      <div className="detail-meta">
        <span>ID: {item.id}</span>
        <span>소스: {item.source_name ?? '-'}</span>
        <span>발행: {item.published_at_display ?? item.published_at ?? '-'}</span>
        <span>카테고리: {item.category ?? '-'}</span>
      </div>
      {thumbSrc && (
        <p className="detail-thumb">
          <img src={thumbSrc} alt="" style={{ maxWidth: 320, maxHeight: 240, objectFit: 'contain' }} />
        </p>
      )}
      <h3>{item.title}</h3>
      {item.description && <div className="detail-body">{item.description}</div>}
      {item.url && (
        <p>
          <a href={item.url} target="_blank" rel="noopener noreferrer">원문 보기</a>
        </p>
      )}
      {item.author && <p>작성자: {item.author}</p>}
    </div>
  )
}

export default NewsArticleDetail
