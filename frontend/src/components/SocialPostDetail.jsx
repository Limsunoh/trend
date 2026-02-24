import { useState, useEffect } from 'react'
import { useParams, useNavigate } from 'react-router-dom'
import { dataCollectorAPI } from '../services/api'
import { API_BASE } from '../config'

function SocialPostDetail() {
  const { id } = useParams()
  const navigate = useNavigate()
  const [item, setItem] = useState(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState(null)

  useEffect(() => {
    let cancelled = false
    dataCollectorAPI.getSocialPost(id)
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
      <h2>소셜 미디어 게시물 상세</h2>
      <div className="detail-meta">
        <span>ID: {item.id}</span>
        <span>소스: {item.source_name ?? item.platform ?? '-'}</span>
        <span>발행: {item.published_at_display ?? item.published_at ?? '-'}</span>
        {item.subreddit && <span>서브레딧: {item.subreddit}</span>}
        {item.gall_name && <span>갤러리: {item.gall_name}</span>}
      </div>
      {thumbSrc && (
        <p className="detail-thumb">
          <img src={thumbSrc} alt="" style={{ maxWidth: 320, maxHeight: 240, objectFit: 'contain' }} />
        </p>
      )}
      <h3>{item.title ?? '(제목 없음)'}</h3>
      {item.content && <div className="detail-body">{item.content}</div>}
      {item.original_content && item.original_content !== item.content && (
        <details>
          <summary>원문</summary>
          <div className="detail-body">{item.original_content}</div>
        </details>
      )}
      {item.url && (
        <p>
          <a href={item.url} target="_blank" rel="noopener noreferrer">원문 보기</a>
        </p>
      )}
      {item.author && <p>작성자: {item.author}</p>}
    </div>
  )
}

export default SocialPostDetail
