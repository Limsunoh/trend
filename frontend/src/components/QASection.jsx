import { useState, useEffect, useRef } from 'react'
import { qaAPI } from '../services/api'

function QASection() {
  const [messages, setMessages] = useState([])
  const [inputValue, setInputValue] = useState('')
  const [loading, setLoading] = useState(false)
  const [history, setHistory] = useState([])
  const [showSources, setShowSources] = useState({})
  const chatEndRef = useRef(null)

  // 히스토리 로드
  useEffect(() => {
    loadHistory()
  }, [])

  // 새 메시지 추가 시 자동 스크롤
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

  // --- 스타일 ---
  const styles = {
    wrapper: {
      display: 'flex',
      gap: '16px',
      minHeight: '70vh',
    },
    sidebar: {
      width: '220px',
      flexShrink: 0,
      background: '#fff',
      borderRadius: '8px',
      border: '1px solid #e0e0e0',
      padding: '12px',
      overflowY: 'auto',
      maxHeight: '75vh',
    },
    sidebarTitle: {
      fontSize: '14px',
      fontWeight: 'bold',
      color: '#2c3e50',
      marginBottom: '8px',
      paddingBottom: '8px',
      borderBottom: '2px solid #3498db',
    },
    newChatBtn: {
      width: '100%',
      padding: '8px',
      marginBottom: '10px',
      background: '#3498db',
      color: '#fff',
      border: 'none',
      borderRadius: '6px',
      cursor: 'pointer',
      fontSize: '13px',
    },
    historyItem: {
      padding: '8px 10px',
      marginBottom: '4px',
      borderRadius: '6px',
      cursor: 'pointer',
      fontSize: '13px',
      color: '#555',
      whiteSpace: 'nowrap',
      overflow: 'hidden',
      textOverflow: 'ellipsis',
      transition: 'background 0.15s',
    },
    chatArea: {
      flex: 1,
      display: 'flex',
      flexDirection: 'column',
      background: '#fff',
      borderRadius: '8px',
      border: '1px solid #e0e0e0',
      overflow: 'hidden',
    },
    chatHeader: {
      padding: '14px 20px',
      borderBottom: '1px solid #e0e0e0',
      fontWeight: 'bold',
      fontSize: '16px',
      color: '#2c3e50',
    },
    chatMessages: {
      flex: 1,
      overflowY: 'auto',
      padding: '20px',
      display: 'flex',
      flexDirection: 'column',
      gap: '12px',
      maxHeight: '55vh',
    },
    userBubble: {
      alignSelf: 'flex-end',
      background: '#3498db',
      color: '#fff',
      padding: '10px 16px',
      borderRadius: '16px 16px 4px 16px',
      maxWidth: '70%',
      lineHeight: '1.5',
      fontSize: '14px',
    },
    assistantBubble: {
      alignSelf: 'flex-start',
      background: '#f8f9fa',
      border: '1px solid #e0e0e0',
      padding: '10px 16px',
      borderRadius: '16px 16px 16px 4px',
      maxWidth: '70%',
      lineHeight: '1.6',
      fontSize: '14px',
      color: '#333',
      whiteSpace: 'pre-wrap',
    },
    sourcesToggle: {
      marginTop: '6px',
      background: 'none',
      border: 'none',
      color: '#3498db',
      cursor: 'pointer',
      fontSize: '12px',
      padding: 0,
    },
    sourcesList: {
      marginTop: '8px',
      padding: '8px 12px',
      background: '#f0f4f8',
      borderRadius: '8px',
      fontSize: '12px',
      lineHeight: '1.6',
    },
    sourceItem: {
      padding: '4px 0',
      borderBottom: '1px solid #e8e8e8',
    },
    sourceLink: {
      color: '#3498db',
      textDecoration: 'none',
    },
    loadingDots: {
      alignSelf: 'flex-start',
      padding: '10px 16px',
      background: '#f8f9fa',
      border: '1px solid #e0e0e0',
      borderRadius: '16px 16px 16px 4px',
      fontSize: '14px',
      color: '#999',
    },
    inputArea: {
      display: 'flex',
      gap: '8px',
      padding: '12px 20px',
      borderTop: '1px solid #e0e0e0',
      background: '#fafafa',
    },
    input: {
      flex: 1,
      padding: '10px 14px',
      border: '1px solid #ddd',
      borderRadius: '8px',
      fontSize: '14px',
      outline: 'none',
    },
    sendBtn: {
      padding: '10px 20px',
      background: '#3498db',
      color: '#fff',
      border: 'none',
      borderRadius: '8px',
      cursor: 'pointer',
      fontSize: '14px',
      fontWeight: 'bold',
    },
    sendBtnDisabled: {
      padding: '10px 20px',
      background: '#bdc3c7',
      color: '#fff',
      border: 'none',
      borderRadius: '8px',
      cursor: 'not-allowed',
      fontSize: '14px',
      fontWeight: 'bold',
    },
    emptyState: {
      flex: 1,
      display: 'flex',
      alignItems: 'center',
      justifyContent: 'center',
      color: '#aaa',
      fontSize: '15px',
    },
    typeBadge: (type) => ({
      display: 'inline-block',
      padding: '1px 6px',
      borderRadius: '4px',
      fontSize: '11px',
      fontWeight: 'bold',
      marginRight: '6px',
      color: '#fff',
      background: type === 'news' ? '#27ae60' : '#8e44ad',
    }),
  }

  return (
    <div className="section">
      <div style={styles.wrapper}>
        {/* 히스토리 사이드바 */}
        <div style={styles.sidebar}>
          <div style={styles.sidebarTitle}>대화 히스토리</div>
          <button style={styles.newChatBtn} onClick={handleNewChat}>
            + 새 대화
          </button>
          {history.length === 0 && (
            <div style={{ fontSize: '13px', color: '#aaa', textAlign: 'center' }}>
              아직 대화 기록이 없습니다
            </div>
          )}
          {history.map((item) => (
            <div
              key={item.id}
              style={styles.historyItem}
              onClick={() => handleHistoryClick(item)}
              onMouseEnter={(e) => (e.currentTarget.style.background = '#f0f4f8')}
              onMouseLeave={(e) => (e.currentTarget.style.background = 'transparent')}
              title={item.query_text}
            >
              {item.query_text}
            </div>
          ))}
        </div>

        {/* 채팅 영역 */}
        <div style={styles.chatArea}>
          <div style={styles.chatHeader}>Q&A 트렌드 질문</div>

          <div style={styles.chatMessages}>
            {messages.length === 0 && !loading && (
              <div style={styles.emptyState}>
                질문을 입력하면 수집된 뉴스와 커뮤니티 데이터를 기반으로 답변합니다.
              </div>
            )}

            {messages.map((msg, idx) => (
              <div key={idx}>
                {msg.role === 'user' ? (
                  <div style={styles.userBubble}>{msg.content}</div>
                ) : (
                  <div>
                    <div style={styles.assistantBubble}>{msg.content}</div>
                    {msg.sources && msg.sources.length > 0 && (
                      <>
                        <button
                          style={styles.sourcesToggle}
                          onClick={() => toggleSources(idx)}
                        >
                          {showSources[idx]
                            ? '▲ 출처 숨기기'
                            : `▼ 출처 보기 (${msg.sources.length}건)`}
                        </button>
                        {showSources[idx] && (
                          <div style={styles.sourcesList}>
                            {msg.sources.map((src, sIdx) => (
                              <div key={sIdx} style={styles.sourceItem}>
                                <span style={styles.typeBadge(src.type)}>
                                  {src.type === 'news' ? '뉴스' : '커뮤니티'}
                                </span>
                                {src.url ? (
                                  <a
                                    href={src.url}
                                    target="_blank"
                                    rel="noopener noreferrer"
                                    style={styles.sourceLink}
                                  >
                                    {src.excerpt || src.source_display || src.url}
                                  </a>
                                ) : (
                                  <span>{src.excerpt || src.source_display || '출처 정보 없음'}</span>
                                )}
                                {src.published_at && (
                                  <span style={{ color: '#999', marginLeft: '8px', fontSize: '11px' }}>
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
              <div style={styles.loadingDots}>답변 생성 중...</div>
            )}

            <div ref={chatEndRef} />
          </div>

          {/* 입력 영역 */}
          <div style={styles.inputArea}>
            <input
              type="text"
              value={inputValue}
              onChange={(e) => setInputValue(e.target.value)}
              onKeyDown={handleKeyDown}
              placeholder="트렌드에 대해 질문하세요..."
              style={styles.input}
              disabled={loading}
            />
            <button
              onClick={handleSubmit}
              disabled={loading || !inputValue.trim()}
              style={
                loading || !inputValue.trim()
                  ? styles.sendBtnDisabled
                  : styles.sendBtn
              }
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
