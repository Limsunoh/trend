import { useState } from 'react'
import DataCollectorSection from './DataCollectorSection'
import AnalyzerSection from './AnalyzerSection'
import '../index.css'

function Dashboard() {
  const [activeTab, setActiveTab] = useState('data-collector')

  return (
    <div className="container">
      <div className="header">
        <h1>트렌드 분석 대시보드</h1>
        <div className="nav">
          <button
            className={activeTab === 'data-collector' ? 'active' : ''}
            onClick={() => setActiveTab('data-collector')}
          >
            데이터 수집
          </button>
          <button
            className={activeTab === 'analyzer' ? 'active' : ''}
            onClick={() => setActiveTab('analyzer')}
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
