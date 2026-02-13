import { useEffect, useState } from 'react'
import { useSearchParams } from 'react-router-dom'
import DataCollectorSection from './DataCollectorSection'
import AnalyzerSection from './AnalyzerSection'
import '../index.css'

const SECTION_PARAM = 'section'

function Dashboard() {
  const [searchParams, setSearchParams] = useSearchParams()
  const sectionFromUrl = searchParams.get(SECTION_PARAM) || 'data-collector'
  const [activeTab, setActiveTab] = useState(sectionFromUrl)

  // URL과 탭 동기화 (뒤로가기 시 분석 결과 탭 복원)
  useEffect(() => {
    const section = searchParams.get(SECTION_PARAM) || 'data-collector'
    if (section === 'data-collector' || section === 'analyzer') {
      setActiveTab(section)
    }
  }, [searchParams])

  const handleTabChange = (tab) => {
    setActiveTab(tab)
    setSearchParams((prev) => {
      const next = new URLSearchParams(prev)
      next.set(SECTION_PARAM, tab === 'data-collector' ? 'data-collector' : 'analyzer')
      return next
    })
  }

  return (
    <div className="container">
      <div className="header">
        <h1>트렌드 분석 대시보드</h1>
        <div className="nav">
          <button
            className={activeTab === 'data-collector' ? 'active' : ''}
            onClick={() => handleTabChange('data-collector')}
          >
            데이터 수집
          </button>
          <button
            className={activeTab === 'analyzer' ? 'active' : ''}
            onClick={() => handleTabChange('analyzer')}
          >
            분석 결과
          </button>
        </div>
      </div>

      {activeTab === 'data-collector' && <DataCollectorSection />}
      {activeTab === 'analyzer' && <AnalyzerSection />}
    </div>
  )
}

export default Dashboard
