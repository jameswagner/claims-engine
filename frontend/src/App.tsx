import { BrowserRouter, Route, Routes } from 'react-router-dom'
import { ClaimDetail } from './pages/ClaimDetail'
import { ClaimsList } from './pages/ClaimsList'
import { Dashboard } from './pages/Dashboard'

function App() {
  return (
    <BrowserRouter>
      <Routes>
        <Route path="/" element={<Dashboard />} />
        <Route path="/claims" element={<ClaimsList />} />
        <Route path="/claims/:id" element={<ClaimDetail />} />
      </Routes>
    </BrowserRouter>
  )
}

export default App
