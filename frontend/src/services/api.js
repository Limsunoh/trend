import axios from 'axios'

const DASHBOARD_BASE = 'http://localhost:8000/api/dashboard'
const ANALYZER_BASE = 'http://localhost:8000/api/analyzer'
const QA_BASE = 'http://localhost:8000/api/user_qa'

const dashboardApi = axios.create({
  baseURL: DASHBOARD_BASE,
  headers: { 'Content-Type': 'application/json' },
})

const analyzerApi = axios.create({
  baseURL: ANALYZER_BASE,
  headers: { 'Content-Type': 'application/json' },
})

const qaApi = axios.create({
  baseURL: QA_BASE,
  headers: { 'Content-Type': 'application/json' },
})

// Data Collector APIs (뉴스 기사·소셜 미디어 게시물만)
export const dataCollectorAPI = {
  getNewsArticles: (params = {}) => dashboardApi.get('/news/', { params }),
  getNewsArticle: (id) => dashboardApi.get(`/news/${id}/`),
  getSocialPosts: (params = {}) => dashboardApi.get('/social/', { params }),
  getSocialPost: (id) => dashboardApi.get(`/social/${id}/`),
}

// Analyzer APIs (api/analyzer/ 기준)
export const analyzerAPI = {
  getAnalysisResults: (params = {}) => analyzerApi.get('/analysis-results/', { params }),
  getAnalysisResult: (id) => analyzerApi.get(`/analysis-results/${id}/`),
  getKeywordsAnalysis: (params = {}) => analyzerApi.get('/analysis/keywords/', { params }),
  getComparePlatformsAnalysis: (params = {}) => analyzerApi.get('/analysis/compare-platforms/', { params }),
  getHotKeywordsAnalysis: (params = {}) => analyzerApi.get('/analysis/hot-keywords/', { params }),
  getTimeLagAnalysis: (params = {}) => analyzerApi.get('/analysis/time-lag/', { params }),
  getSurgeKeywordsAnalysis: (params = {}) => analyzerApi.get('/analysis/surge-keywords/', { params }),
  getTrendSynchronizationAnalysis: (params = {}) => analyzerApi.get('/analysis/trend-synchronization/', { params }),
  getHourlyTrendsAnalysis: (params = {}) => analyzerApi.get('/analysis/hourly-trends/', { params }),
  getEngagementKeywordsAnalysis: (params = {}) => analyzerApi.get('/analysis/engagement-keywords/', { params }),
}

// QA APIs (api/user_qa/ 기준)
export const qaAPI = {
  submitQuery: (data) => qaApi.post('/query/', data),
  getHistory: (params = {}) => qaApi.get('/history/', { params }),
  getHistoryItem: (id) => qaApi.get(`/history/${id}/`),
}

export default dashboardApi
