import axios from 'axios'

const API_BASE_URL = 'http://localhost:8000/api/dashboard'

const api = axios.create({
  baseURL: API_BASE_URL,
  headers: {
    'Content-Type': 'application/json',
  },
})

// Data Collector APIs
export const dataCollectorAPI = {
  // 뉴스 소스
  getNewsSources: (params = {}) => {
    return api.get('/sources/', { params })
  },
  getNewsSource: (id) => {
    return api.get(`/sources/${id}/`)
  },

  // 뉴스 기사
  getNewsArticles: (params = {}) => {
    return api.get('/news/', { params })
  },
  getNewsArticle: (id) => {
    return api.get(`/news/${id}/`)
  },

  // 소셜 미디어 게시물
  getSocialPosts: (params = {}) => {
    return api.get('/social/', { params })
  },
  getSocialPost: (id) => {
    return api.get(`/social/${id}/`)
  },

  // 소셜 미디어 소스
  getSocialSources: (params = {}) => {
    return api.get('/social-sources/', { params })
  },
  getSocialSource: (id) => {
    return api.get(`/social-sources/${id}/`)
  },
}

// Analyzer APIs
export const analyzerAPI = {
  // 전체 분석 결과
  getAnalysisResults: (params = {}) => {
    return api.get('/analysis-results/', { params })
  },
  getAnalysisResult: (id) => {
    return api.get(`/analysis-results/${id}/`)
  },

  // 각 분석 타입별
  getKeywordsAnalysis: (params = {}) => {
    return api.get('/analysis/keywords/', { params })
  },
  getComparePlatformsAnalysis: (params = {}) => {
    return api.get('/analysis/compare-platforms/', { params })
  },
  getHotKeywordsAnalysis: (params = {}) => {
    return api.get('/analysis/hot-keywords/', { params })
  },
  getTimeLagAnalysis: (params = {}) => {
    return api.get('/analysis/time-lag/', { params })
  },
  getSurgeKeywordsAnalysis: (params = {}) => {
    return api.get('/analysis/surge-keywords/', { params })
  },
  getTrendSynchronizationAnalysis: (params = {}) => {
    return api.get('/analysis/trend-synchronization/', { params })
  },
  getHourlyTrendsAnalysis: (params = {}) => {
    return api.get('/analysis/hourly-trends/', { params })
  },
  getKeywordOccurrenceTimesAnalysis: (params = {}) => {
    return api.get('/analysis/keyword-occurrence-times/', { params })
  },
  getKeywordTimelineAnalysis: (params = {}) => {
    return api.get('/analysis/keyword-timeline/', { params })
  },
  getMultipleKeywordsTimelineAnalysis: (params = {}) => {
    return api.get('/analysis/multiple-keywords-timeline/', { params })
  },
  getEngagementKeywordsAnalysis: (params = {}) => {
    return api.get('/analysis/engagement-keywords/', { params })
  },
}

export default api
