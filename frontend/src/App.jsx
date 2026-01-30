import { BrowserRouter, Routes, Route } from 'react-router-dom'
import Dashboard from './components/Dashboard'
import NewsArticleDetail from './components/NewsArticleDetail'
import SocialPostDetail from './components/SocialPostDetail'
import AnalysisDetail from './components/AnalysisDetail'
import './App.css'

function App() {
  return (
    <BrowserRouter>
      <div className="App">
        <Routes>
          <Route path="/" element={<Dashboard />} />
          <Route path="/news/:id" element={<NewsArticleDetail />} />
          <Route path="/social/:id" element={<SocialPostDetail />} />
          <Route path="/analysis/:id" element={<AnalysisDetail />} />
        </Routes>
      </div>
    </BrowserRouter>
  )
}

export default App
