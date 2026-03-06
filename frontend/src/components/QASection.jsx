import { useState, useEffect, useRef } from 'react'
import { qaAPI } from '../services/api'

function QASection() {
  const [messages, setMessages] = useState([])
  const [inputValue, setInputValue] = useState('')
  const [loading, setLoading] = useState(false)
  const [history, setHistory] = useState([])
  const [showSources, setShowSources] = useState({})
  const chatEndRef = useRef(null)

  useEffect(() => {
    loadHistory()
  }, [])

  useEffect(() => {
    chatEndRef.current?.scrollIntoView({ behavior: 'smooth' })
  }, [messages, loading])

  const loadHistory = async () => {
    try {
      const res = await qaAPI.getHistory({ page_size: 20 })
      const items = res.data?.results ?? res.data ?? []
      setHistory(items)
    } catch (err) {
      console.error('히스토리 로드 실패:', err)
    }
  }

  const handleSubmit = async () => {
    const query = inputValue.trim()
    if (!query || loading) return

    setInputValue('')
    setMessages((prev) => [...prev, { role: 'user', content: query }])
    setLoading(true)

    try {
      const res = await qaAPI.submitQuery({ query })
      const data = res.data
      setMessages((prev) => [
        ...prev,
        {
          role: 'assistant',
          content: data.answer || '답변을 생성하지 못했습니다.',
          sources: data.sources || [],
        },
      ])
      loadHistory()
    } catch (err) {
      const errMsg =
        err.response?.data?.error || err.message || '오류가 발생했습니다.'
      setMessages((prev) => [
        ...prev,
        { role: 'assistant', content: `오류: ${errMsg}`, sources: [] },
      ])
    } finally {
      setLoading(false)
    }
  }

  const handleKeyDown = (e) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault()
      handleSubmit()
    }
  }

  const toggleSources = (index) => {
    setShowSources((prev) => ({ ...prev, [index]: !prev[index] }))
  }

  const handleHistoryClick = async (item) => {
    setMessages([
      { role: 'user', content: item.query_text },
      {
        role: 'assistant',
        content: item.answer_text,
        sources: item.sources || [],
      },
    ])
    setShowSources({})
  }

  const handleNewChat = () => {
    setMessages([])
    setShowSources({})
    setInputValue('')
  }

  return (
    <div className="section">
      <div className="qa-wrapper">
        {/* 히스토리 사이드바 */}
        <div className="qa-sidebar">
          <div className="qa-sidebar-title">대화 히스토리</div>
          <button className="qa-new-chat-btn" onClick={handleNewChat}>
            + 새 대화
          </button>
          {history.length === 0 && (
            <div className="qa-sidebar-empty">
              아직 대화 기록이 없습니다
            </div>
          )}
          {history.map((item) => (
            <div
              key={item.id}
              className="qa-history-item"
              onClick={() => handleHistoryClick(item)}
              title={item.query_text}
            >
              {item.query_text}
            </div>
          ))}
        </div>

        {/* 채팅 영역 */}
        <div className="qa-chat-area">
          <div className="qa-chat-header">Q&A 트렌드 질문</div>

          <div className="qa-chat-messages">
            {messages.length === 0 && !loading && (
              <div className="qa-empty-state">
                질문을 입력하면 수집된 뉴스와 커뮤니티 데이터를 기반으로 답변합니다.
              </div>
            )}

            {messages.map((msg, idx) => (
              <div key={idx}>
                {msg.role === 'user' ? (
                  <div className="qa-bubble-user">{msg.content}</div>
                ) : (
                  <div>
                    <div className="qa-bubble-assistant">{msg.content}</div>
                    {msg.sources && msg.sources.length > 0 && (
                      <>
                        <button
                          className="qa-sources-toggle"
                          onClick={() => toggleSources(idx)}
                        >
                          {showSources[idx]
                            ? '▲ 출처 숨기기'
                            : `▼ 출처 보기 (${msg.sources.length}건)`}
                        </button>
                        {showSources[idx] && (
                          <div className="qa-sources-list">
                            {msg.sources.map((src, sIdx) => (
                              <div key={sIdx} className="qa-source-item">
                                <span className={`qa-type-badge ${src.type === 'news' ? 'news' : src.type === 'analysis' ? 'analysis' : 'social'}`}>
                                  {src.type === 'news' ? '뉴스' : src.type === 'analysis' ? '분석' : '커뮤니티'}
                                </span>
                                {src.url ? (
                                  <a
                                    href={src.url}
                                    target="_blank"
                                    rel="noopener noreferrer"
                                    className="qa-source-link"
                                  >
                                    {src.excerpt || src.source_display || src.url}
                                  </a>
                                ) : (
                                  <span>{src.excerpt || src.source_display || '출처 정보 없음'}</span>
                                )}
                                {src.published_at && (
                                  <span className="qa-source-date">
                                    {new Date(src.published_at).toLocaleDateString('ko-KR')}
                                  </span>
                                )}
                              </div>
                            ))}
                          </div>
                        )}
                      </>
                    )}
                  </div>
                )}
              </div>
            ))}

            {loading && (
              <div className="qa-loading-dots">답변 생성 중...</div>
            )}

            <div ref={chatEndRef} />
          </div>

          {/* 입력 영역 */}
          <div className="qa-input-area">
            <input
              type="text"
              value={inputValue}
              onChange={(e) => setInputValue(e.target.value)}
              onKeyDown={handleKeyDown}
              placeholder="트렌드에 대해 질문하세요..."
              className="qa-input"
              disabled={loading}
            />
            <button
              onClick={handleSubmit}
              disabled={loading || !inputValue.trim()}
              className="qa-send-btn"
            >
              전송
            </button>
          </div>
        </div>
      </div>
    </div>
  )
}

export default QASection
